"""Tipos del subsistema de reconocimiento de voz."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Word:
    """Una unidad con marca temporal devuelta por Whisper.

    En japones no son palabras: Whisper emite trozos de subpalabra, a menudo de
    uno o dos caracteres. Para LocalAgreement es una ventaja, porque la
    granularidad fina hace que el prefijo confirmado avance de forma mas suave.
    La segmentacion linguistica de verdad la hara Sudachi en la fase 2.
    """

    start: float
    """Segundos absolutos desde el inicio de la sesion."""

    end: float
    text: str
    probability: float = 1.0


@dataclass(slots=True)
class Sentence:
    """Frase cerrada, lista para traducir y analizar."""

    segment_id: int
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    reason: str = "punctuation"
    """Por que se cerro: ``punctuation``, ``silence`` o ``max_length``."""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(slots=True)
class QualitySignals:
    """Senales que devuelve Whisper y que sirven para detectar alucinaciones."""

    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 1.0


@dataclass(slots=True)
class TranscribeResult:
    words: list[Word]
    quality: QualitySignals
    inference_ms: float
    audio_s: float
    """Duracion de la ventana analizada. ``inference_ms / audio_s`` da el RTF."""

    @property
    def rtf(self) -> float:
        return (self.inference_ms / 1000.0) / self.audio_s if self.audio_s else 0.0
