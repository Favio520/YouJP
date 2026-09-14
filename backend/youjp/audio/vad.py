"""Deteccion de actividad de voz con Silero VAD sobre ONNX Runtime.

Se ejecuta **antes** del ASR, no dentro de el. Cumple tres funciones distintas:

1. Es el portero contra las alucinaciones de Whisper. Sobre silencio o musica,
   Whisper en japones inventa frases completas y plausibles (agradecimientos de
   fin de video, peticiones de suscripcion). Si el audio no contiene voz, no
   llega al modelo y el problema no existe.
2. Decide cuando cerrar una frase, por silencio sostenido.
3. Evita gastar GPU en reejecutar sobre tramos mudos.

Cuesta menos de 1 ms de CPU por ventana de 32 ms, asi que es gratis comparado
con cualquier alternativa.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import onnxruntime as ort

log = logging.getLogger(__name__)


class SileroVAD:
    """Envoltorio del modelo ONNX de Silero.

    Se adapta a la firma del modelo en vez de asumirla: v5 usa un unico tensor
    ``state`` y ventanas de 512 muestras a 16 kHz; v4 usaba ``h``/``c`` y
    ventanas de 1536. Si el fichero cambia, esto no se rompe en silencio.
    """

    def __init__(
        self,
        model_path: str | Path,
        *,
        sample_rate: int = 16_000,
        num_threads: int = 1,
    ) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"no encuentro el modelo de VAD en {self.model_path}. "
                "Descargalo con: uv run python ../scripts/fetch_models.py"
            )
        if sample_rate not in (8_000, 16_000):
            raise ValueError("Silero solo admite 8 kHz o 16 kHz")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = num_threads
        opts.intra_op_num_threads = num_threads
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._sess = ort.InferenceSession(
            str(self.model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )

        self._input_names = [i.name for i in self._sess.get_inputs()]
        self._uses_state = "state" in self._input_names  # v5
        if not self._uses_state and "h" not in self._input_names:
            raise RuntimeError(
                f"firma de VAD no reconocida: entradas {self._input_names}. "
                "Se esperaba Silero v4 (h/c) o v5 (state)."
            )

        self.sample_rate = sample_rate
        # v5 exige exactamente 512 muestras a 16 kHz y 256 a 8 kHz.
        self.window_samples = (512 if sample_rate == 16_000 else 256) if self._uses_state else (
            1536 if sample_rate == 16_000 else 768
        )
        # v5 ademas espera 64 muestras de contexto (32 a 8 kHz) delante de cada
        # ventana: el tensor que entra al modelo es de 576, no de 512. Sin el
        # contexto el modelo no falla ni avisa -- devuelve ~0,001 para todo, lo
        # mismo sobre habla que sobre silencio digital. Es un fallo silencioso
        # que solo se ve comparando dos audios que deberian dar resultados
        # distintos.
        self._context_samples = (64 if sample_rate == 16_000 else 32) if self._uses_state else 0
        self._pending = np.empty(0, dtype=np.float32)
        self.reset()
        log.info(
            "Silero VAD cargado (%s, ventana %d muestras = %.0f ms)",
            "v5" if self._uses_state else "v4",
            self.window_samples,
            1000 * self.window_samples / sample_rate,
        )

    def reset(self) -> None:
        """Reinicia el estado recurrente. Obligatorio tras un seek."""
        if self._uses_state:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._context = np.zeros((1, self._context_samples), dtype=np.float32)
        else:
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._pending = np.empty(0, dtype=np.float32)

    def probabilities(self, pcm: np.ndarray) -> np.ndarray:
        """Probabilidad de voz por ventana completa.

        Las muestras sobrantes quedan guardadas para la siguiente llamada, de
        modo que las ventanas siguen alineadas aunque las tramas de entrada no
        sean multiplo del tamano de ventana.
        """
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        buf = np.concatenate((self._pending, pcm)) if self._pending.size else pcm
        n = len(buf) // self.window_samples
        self._pending = buf[n * self.window_samples :].copy()
        if n == 0:
            return np.empty(0, dtype=np.float32)

        out = np.empty(n, dtype=np.float32)
        sr = np.array(self.sample_rate, dtype=np.int64)
        for i in range(n):
            window = buf[i * self.window_samples : (i + 1) * self.window_samples]
            frame = window.reshape(1, -1)
            if self._uses_state:
                frame = np.concatenate((self._context, frame), axis=1)
                prob, self._state = self._sess.run(
                    None, {"input": frame, "state": self._state, "sr": sr}
                )
                self._context = frame[:, -self._context_samples :]
            else:
                prob, self._h, self._c = self._sess.run(
                    None, {"input": frame, "h": self._h, "c": self._c, "sr": sr}
                )
            out[i] = float(np.asarray(prob).reshape(-1)[0])
        return out


@dataclass(frozen=True, slots=True)
class SpeechEvent:
    kind: Literal["speech_start", "speech_end"]
    time: float
    """Instante absoluto en segundos desde el inicio de la sesion."""


class VADGate:
    """Convierte probabilidades por ventana en eventos de voz con histeresis.

    Dos umbrales en vez de uno: se entra en voz por encima de ``threshold`` y
    solo se sale por debajo de ``release_threshold`` **y** tras
    ``min_silence_ms`` de silencio sostenido. Con un unico umbral el estado
    parpadea en cada pausa entre palabras y el segmentador parte las frases por
    la mitad.
    """

    def __init__(
        self,
        vad: SileroVAD,
        *,
        threshold: float = 0.5,
        release_threshold: float = 0.35,
        min_silence_ms: int = 500,
        speech_pad_ms: int = 200,
        start_time: float = 0.0,
    ) -> None:
        self._vad = vad
        self.threshold = threshold
        self.release_threshold = release_threshold
        self.min_silence_ms = min_silence_ms
        self.speech_pad_ms = speech_pad_ms

        self._window_s = vad.window_samples / vad.sample_rate
        self._t = start_time
        self._triggered = False
        self._silence_since: float | None = None
        self.last_speech_end: float = start_time
        self.last_prob: float = 0.0

    @property
    def now(self) -> float:
        """Instante absoluto ya procesado por el VAD."""
        return self._t

    @property
    def is_speech(self) -> bool:
        return self._triggered

    @property
    def silence_ms(self) -> float:
        """Silencio acumulado desde la ultima voz. 0 si esta hablando."""
        if self._triggered or self._silence_since is None:
            return 0.0
        return 1000.0 * (self._t - self._silence_since)

    def push(self, pcm: np.ndarray) -> list[SpeechEvent]:
        """Procesa audio nuevo y devuelve los eventos que se hayan producido."""
        events: list[SpeechEvent] = []
        pad = self.speech_pad_ms / 1000.0
        for prob in self._vad.probabilities(pcm):
            self._t += self._window_s
            self.last_prob = float(prob)

            if not self._triggered:
                if prob >= self.threshold:
                    self._triggered = True
                    self._silence_since = None
                    events.append(
                        SpeechEvent("speech_start", max(0.0, self._t - self._window_s - pad))
                    )
                continue

            if prob >= self.release_threshold:
                self._silence_since = None
                continue

            if self._silence_since is None:
                self._silence_since = self._t
            elif 1000.0 * (self._t - self._silence_since) >= self.min_silence_ms:
                self._triggered = False
                self.last_speech_end = self._silence_since + pad
                events.append(SpeechEvent("speech_end", self.last_speech_end))
                self._silence_since = self._t
        return events

    def reset(self, at_time: float | None = None) -> None:
        """Reinicia tras un seek o una pausa."""
        self._vad.reset()
        if at_time is not None:
            self._t = at_time
            self.last_speech_end = at_time
        self._triggered = False
        self._silence_since = None
