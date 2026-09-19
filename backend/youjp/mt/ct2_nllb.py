"""Traductor dedicado: NLLB-200 destilado sobre CTranslate2.

Es el proveedor del camino caliente. Se ejecuta sobre cada frase final y tiene
que caber holgadamente en el presupuesto de latencia, así que la prioridad es
que sea rápido y predecible, no que sea el mejor traductor posible: para los
matices está el LLM bajo demanda.

Comparte motor con Whisper (CTranslate2), así que no añade ninguna dependencia
nativa nueva. El tokenizador sí necesita ``transformers``, que es la vía
documentada por CTranslate2 para NLLB; no arrastra PyTorch.

Nota sobre el modelo: se usa una conversión a CTranslate2 ya publicada, porque
convertirlo aquí exigiría instalar PyTorch (2,5 GB) solo para hacer una
conversión de una vez.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path

from youjp.config import Settings
from youjp.cuda_setup import enable_cuda_dlls
from youjp.mt.base import Translation
from youjp.mt.languages import NLLB_TARGETS, TargetLanguage, resolve_target

log = logging.getLogger(__name__)


class Nllb200Provider:
    """Traductor NLLB-200. Ignora el contexto: es un modelo frase a frase."""

    name = "nllb200"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._translator = None
        self._tokenizer = None

    # -- ciclo de vida -----------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._translator is not None

    def load(self) -> None:
        if self._translator is not None:
            return
        enable_cuda_dlls()

        import ctranslate2
        import transformers

        s = self.settings
        local = self._ensure_model()

        t0 = time.perf_counter()
        log.info("cargando traductor %s en %s (%s)...", s.mt_model, s.mt_device, s.mt_compute_type)
        self._translator = ctranslate2.Translator(
            str(local), device=s.mt_device, compute_type=s.mt_compute_type
        )
        # El tokenizador sale del mismo directorio: la conversión trae consigo
        # sentencepiece.bpe.model y tokenizer.json, así que no hay que bajar
        # nada de otro repositorio ni arriesgarse a mezclar vocabularios.
        self._tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(local), src_lang=s.mt_source_lang
        )
        log.info("traductor listo en %.0f ms", (time.perf_counter() - t0) * 1000)

    def _ensure_model(self) -> Path:
        from huggingface_hub import snapshot_download

        s = self.settings
        candidate = Path(s.mt_model)
        if candidate.is_dir():
            return candidate
        return Path(
            snapshot_download(
                repo_id=s.mt_model,
                cache_dir=str(s.models_dir / "mt"),
                allow_patterns=[
                    "*.json",
                    "*.model",
                    "model.bin",
                    "*.txt",
                ],
            )
        )

    def unload(self) -> None:
        if self._translator is None:
            return
        del self._translator
        self._translator = None
        self._tokenizer = None
        import gc

        gc.collect()
        log.info("traductor descargado")

    def warmup(self) -> float:
        self.load()
        t0 = time.perf_counter()
        self.translate("今日はいい天気です。")
        return (time.perf_counter() - t0) * 1000

    # -- traducción --------------------------------------------------------

    def translate(
        self, text: str, context: Sequence[str] = (), *, target: TargetLanguage | None = None
    ) -> Translation:
        language = resolve_target(target, self.settings.mt_target_lang)
        del context  # NLLB traduce frase a frase; el contexto es para el LLM
        self.load()
        s = self.settings
        source_text = text.strip()
        if not source_text:
            return Translation(text="", provider=self.name, latency_ms=0.0)

        t0 = time.perf_counter()
        # La secuencia exacta viene de la guía de CTranslate2 para NLLB: el
        # token de idioma de origen lo añade el tokenizador (src_lang), el de
        # destino se fuerza como prefijo, y la primera unidad de la hipótesis
        # es ese propio token, que hay que quitar antes de decodificar.
        source = self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(source_text))
        results = self._translator.translate_batch(
            [source],
            target_prefix=[[NLLB_TARGETS[language]]],
            beam_size=s.mt_beam_size,
            max_decoding_length=s.mt_max_tokens,
        )
        hypothesis = results[0].hypotheses[0][1:]
        output = self._tokenizer.decode(self._tokenizer.convert_tokens_to_ids(hypothesis))

        return Translation(
            text=output.strip(),
            provider=self.name,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
