"""Traductor por LLM, vía Ollama.

Existe para poder comparar contra NLLB con datos reales, que es lo que quedó
pendiente en el ADR 0003, y como reemplazo si la calidad de NLLB no da la talla.

A diferencia de NLLB, este sí usa las frases anteriores como contexto, que es
justamente donde un LLM aporta algo: resolver a quién se refiere un sujeto
omitido, mantener el registro y no cambiar la traducción de un término a mitad
de conversación.

El prompt es deliberadamente estricto. Un modelo de instrucciones al que se le
pide "traduce" tiende a añadir explicaciones, notas culturales y comillas, y
todo eso acaba en pantalla encima del vídeo.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence

import httpx

from youjp.config import Settings
from youjp.mt.base import Translation

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Eres un traductor de japonés a español para subtítulos. "
    "Devuelves ÚNICAMENTE la traducción de la última línea, en una sola línea, "
    "sin comillas, sin el texto japonés, sin explicaciones y sin notas. "
    "Mantienes el registro del original: si es conversación informal, traduces "
    "en informal. Si la línea está incompleta, traduces lo que hay sin inventar "
    "el final."
)

# Los modelos con modo de razonamiento emiten el bloque de pensamiento en la
# respuesta. En un subtítulo eso es ruido.
_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_WRAPPING_QUOTES = re.compile(r'^["「“\'](.*)["」”\']$', re.DOTALL)


class LlmProvider:
    name = "llm"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.Client | None = None

    # -- ciclo de vida -----------------------------------------------------

    def load(self) -> None:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.settings.llm_url, timeout=self.settings.llm_timeout_s
            )

    def unload(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def warmup(self) -> float:
        """Primera traducción para pagar la carga del modelo antes de empezar.

        Medido: la primera llamada en frío cuesta unos 30 s mientras Ollama sube
        el modelo a la GPU. Sin calentar, esos 30 s se los come la primera frase
        que diga el vídeo.
        """
        t0 = time.perf_counter()
        self.translate("今日はいい天気です。")
        ms = (time.perf_counter() - t0) * 1000
        log.info("traductor calentado en %.0f ms", ms)
        return ms

    def available(self) -> bool:
        """Comprueba que Ollama responde y tiene el modelo pedido."""
        self.load()
        assert self._client is not None
        try:
            tags = self._client.get("/api/tags", timeout=3.0).json()
        except httpx.HTTPError as exc:
            log.warning("Ollama no responde en %s: %s", self.settings.llm_url, exc)
            return False
        names = {m.get("name", "") for m in tags.get("models", [])}
        if self.settings.llm_model not in names:
            log.warning(
                "Ollama no tiene %s. Descargalo con: ollama pull %s\nDisponibles: %s",
                self.settings.llm_model,
                self.settings.llm_model,
                ", ".join(sorted(names)) or "(ninguno)",
            )
            return False
        return True

    def report_residents(self) -> None:
        """Avisa si Ollama tiene otros modelos ocupando la GPU.

        Ollama no descarga un modelo al cargar otro: los deja residentes hasta
        que expira su keep_alive. En una tarjeta de 6 GB eso importa mucho --
        durante las pruebas del 14-09-2026, un qwen3:1.7b olvidado de un
        experimento anterior se estaba comiendo 1 398 MiB y hacia parecer que el
        traductor no cabia.
        """
        self.load()
        assert self._client is not None
        try:
            running = self._client.get("/api/ps", timeout=3.0).json().get("models", [])
        except httpx.HTTPError:
            return

        ajenos = [m for m in running if m.get("name") != self.settings.llm_model]
        if not ajenos:
            return
        detalle = ", ".join(
            f"{m.get('name')} ({m.get('size_vram', 0) / 1024**2:.0f} MiB)" for m in ajenos
        )
        log.warning(
            "Ollama tiene otros modelos ocupando memoria: %s. "
            "Descargalos con: ollama stop <nombre>",
            detalle,
        )

    # -- traducción --------------------------------------------------------

    def _build_prompt(self, text: str, context: Sequence[str]) -> str:
        if not context:
            return f"Línea a traducir:\n{text}"
        previas = "\n".join(context)
        return (
            "Contexto (líneas anteriores, NO las traduzcas):\n"
            f"{previas}\n\n"
            f"Línea a traducir:\n{text}"
        )

    def translate(self, text: str, context: Sequence[str] = ()) -> Translation:
        self.load()
        assert self._client is not None
        s = self.settings
        source = text.strip()
        if not source:
            return Translation(text="", provider=self.name, latency_ms=0.0)

        t0 = time.perf_counter()
        try:
            response = self._client.post(
                "/api/chat",
                json={
                    "model": s.llm_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": self._build_prompt(source, context)},
                    ],
                    "stream": False,
                    # Desactiva el modo de razonamiento en los modelos que lo
                    # tienen: para traducir una línea no aporta nada y multiplica
                    # el tiempo de respuesta por cinco o más.
                    "think": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": s.mt_max_tokens,
                        "num_gpu": s.llm_num_gpu,
                        "num_ctx": s.llm_num_ctx,
                    },
                    # Mantiene el modelo residente entre frases. Sin esto Ollama
                    # lo descarga tras unos minutos de pausa y la siguiente
                    # frase paga 30 s de carga.
                    "keep_alive": s.llm_keep_alive,
                },
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
        except httpx.HTTPError as exc:
            log.warning("fallo del LLM al traducir: %s", exc)
            return Translation(text="", provider=self.name, latency_ms=0.0)

        return Translation(
            text=_clean(content),
            provider=self.name,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


def _clean(raw: str) -> str:
    """Quita el bloque de razonamiento, comillas envolventes y saltos de línea.

    Un subtítulo es una línea. Todo lo demás sobra.
    """
    text = _THINK.sub("", raw).strip()
    text = " ".join(text.split())
    match = _WRAPPING_QUOTES.match(text)
    if match:
        text = match.group(1).strip()
    return text
