"""Reconocimiento de voz y politica de streaming."""

from youjp.asr.capabilities import supports_word_timestamps
from youjp.asr.engine import WhisperEngine, interpolate_words
from youjp.asr.hallucination import Rejection, repetition_ratio, screen
from youjp.asr.hypothesis import HypothesisBuffer
from youjp.asr.segmenter import SentenceSegmenter
from youjp.asr.types import QualitySignals, Sentence, TranscribeResult, Word

__all__ = [
    "HypothesisBuffer",
    "QualitySignals",
    "Rejection",
    "Sentence",
    "SentenceSegmenter",
    "TranscribeResult",
    "WhisperEngine",
    "Word",
    "interpolate_words",
    "repetition_ratio",
    "screen",
    "supports_word_timestamps",
]
