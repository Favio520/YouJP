"""Cierre de frases sobre el texto ya confirmado.

Whisper puntua el japones de forma irregular: hay tramos largos sin un solo
``。``. Depender solo de los signos deja frases de treinta segundos, y
depender solo del silencio parte las frases en cada pausa para respirar. El
segmentador cierra por lo que ocurra antes de estas tres cosas:

1. signo de fin de frase (``。``, ``！``, ``？``);
2. silencio sostenido detectado por el VAD;
3. longitud maxima, como red de seguridad.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from youjp.asr.types import Sentence, Word

log = logging.getLogger(__name__)


class SentenceSegmenter:
    def __init__(
        self,
        *,
        end_chars: str = "。！？",
        max_chars: int = 60,
        first_id: int = 1,
    ) -> None:
        self.end_chars = set(end_chars)
        self.max_chars = max_chars
        self._next_id = first_id
        self._pending: list[Word] = []

    # -- estado ------------------------------------------------------------

    @property
    def pending_text(self) -> str:
        return "".join(w.text.strip() for w in self._pending)

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    @property
    def pending_start(self) -> float | None:
        """Instante absoluto de la primera palabra pendiente."""
        return self._pending[0].start if self._pending else None

    @property
    def next_segment_id(self) -> int:
        return self._next_id

    # -- entrada -----------------------------------------------------------

    def feed(self, words: Iterable[Word]) -> list[Sentence]:
        """Anade palabras confirmadas y devuelve las frases que se hayan cerrado."""
        closed: list[Sentence] = []
        for word in words:
            self._pending.append(word)
            text = word.text.strip()
            if text and text[-1] in self.end_chars:
                closed.append(self._close("punctuation"))
            elif len(self.pending_text) >= self.max_chars:
                closed.append(self._close("max_length"))
        return closed

    def flush(self, reason: str = "silence") -> Sentence | None:
        """Cierra lo que haya pendiente. Se llama al detectar silencio o al
        terminar la sesion."""
        if not self._pending:
            return None
        return self._close(reason)

    def reset(self) -> None:
        """Descarta lo pendiente sin emitirlo. Se usa tras un seek."""
        self._pending.clear()

    # -- interno -----------------------------------------------------------

    def _close(self, reason: str) -> Sentence:
        words = self._pending
        self._pending = []
        sentence = Sentence(
            segment_id=self._next_id,
            text="".join(w.text.strip() for w in words),
            start=words[0].start,
            end=words[-1].end,
            words=words,
            reason=reason,
        )
        self._next_id += 1
        log.debug("frase %d cerrada por %s: %r", sentence.segment_id, reason, sentence.text)
        return sentence
