"""Politica LocalAgreement-2: convierte a Whisper en un sistema de streaming.

Whisper es codificador-decodificador sobre ventanas de 30 s, no un modelo de
streaming. Si se espera a que el VAD cierre cada intervencion, la latencia es
*duracion de la frase + inferencia*: entre 4 y 10 s en habla continua, y sin
parciales por el camino.

LocalAgreement-2 reejecuta el modelo sobre un buffer que crece y confirma unica-
mente el prefijo en el que coinciden dos pasadas consecutivas. Lo confirmado ya
no cambia nunca, asi que se puede pintar en firme; lo que va detras se muestra en
gris y se reescribe libremente.

El coste es una espera adicional de una pasada (~0,8 s) antes de dar por buena
una palabra. Es el precio de tener parciales estables en lugar de texto que baila.

Referencia: Machacek, Dabre, Bojar, *Turning Whisper into Real-Time Transcription
System* (IJCNLP-AACL 2023), arXiv:2307.14743.
"""

from __future__ import annotations

import logging

from youjp.asr.hallucination import repetition_ratio
from youjp.asr.types import Word

log = logging.getLogger(__name__)


def _norm(text: str) -> str:
    """Normaliza para comparar hipotesis.

    Whisper puede adornar el mismo trozo con espacios segun el contexto en el que
    lo emite. Comparar sin normalizar impediria confirmar prefijos identicos.
    """
    return text.strip()


class HypothesisBuffer:
    """Mantiene el prefijo confirmado y la cola tentativa.

    Uso por iteracion::

        buf.insert(words_de_esta_pasada)
        nuevas = buf.commit()      # palabras que acaban de quedar firmes
        cola = buf.tentative_text  # lo que se pinta en gris
    """

    def __init__(self, *, max_prompt_overlap: int = 6) -> None:
        self.committed: list[Word] = []
        self._previous: list[Word] = []
        self._incoming: list[Word] = []
        self.last_committed_time: float = 0.0
        self.max_prompt_overlap = max_prompt_overlap

    # -- entrada -----------------------------------------------------------

    def insert(self, words: list[Word]) -> None:
        """Registra la hipotesis de la pasada actual.

        Descarta lo que ya cae dentro de la zona confirmada y recorta el solape
        que aparece cuando el modelo repite el ``initial_prompt`` al principio de
        su salida, cosa que hace a menudo.
        """
        fresh = [w for w in words if w.end > self.last_committed_time - 0.1]

        if fresh and self.committed and abs(fresh[0].start - self.last_committed_time) < 1.0:
            limit = min(len(self.committed), len(fresh), self.max_prompt_overlap)
            for n in range(limit, 0, -1):
                tail = "".join(_norm(w.text) for w in self.committed[-n:])
                head = "".join(_norm(w.text) for w in fresh[:n])
                if tail and tail == head:
                    log.debug("recortado solape de prompt de %d unidades: %r", n, tail)
                    del fresh[:n]
                    break

        self._incoming = fresh

    # -- confirmacion ------------------------------------------------------

    def commit(self) -> list[Word]:
        """Confirma el prefijo comun con la pasada anterior.

        Devuelve solo las palabras que pasan a firme en esta llamada.
        """
        newly: list[Word] = []
        while self._incoming and self._previous:
            if _norm(self._incoming[0].text) != _norm(self._previous[0].text):
                break
            word = self._incoming.pop(0)
            self._previous.pop(0)
            newly.append(word)
            self.last_committed_time = word.end

        self.committed.extend(newly)
        self._previous = self._incoming
        self._incoming = []
        return newly

    # -- lectura -----------------------------------------------------------

    @property
    def committed_text(self) -> str:
        return "".join(_norm(w.text) for w in self.committed)

    @property
    def tentative(self) -> list[Word]:
        """Cola no confirmada. Se reemplaza entera en cada actualizacion: nunca
        montes tokens clicables sobre ella."""
        return list(self._previous)

    @property
    def tentative_text(self) -> str:
        return "".join(_norm(w.text) for w in self._previous)

    def prompt(self, max_chars: int, *, max_repeat_ratio: float = 0.5) -> str:
        """Ultimo texto confirmado, para pasarlo como ``initial_prompt``.

        Acotado a proposito: con ``condition_on_previous_text=False`` este es el
        unico contexto que ve el modelo, y realimentar demasiado es justo lo que
        dispara los bucles de alucinacion que se intentan evitar.

        Si la cola confirmada ya es repetitiva, se devuelve vacia: realimentar un
        bucle al modelo es la forma mas segura de perpetuarlo.
        """
        if max_chars <= 0:
            return ""
        tail = self.committed_text[-max_chars:]
        if repetition_ratio(tail) > max_repeat_ratio:
            log.debug("prompt suprimido: la cola confirmada es repetitiva")
            return ""
        return tail

    # -- mantenimiento -----------------------------------------------------

    def drop_committed_before(self, t: float) -> None:
        """Olvida las palabras confirmadas anteriores a ``t``.

        Se llama junto con el recorte del buffer de audio, para que la memoria no
        crezca durante un directo de varias horas. Lo ya emitido al cliente no se
        toca: esto solo afecta al contexto que se sigue arrastrando aqui.
        """
        keep = [w for w in self.committed if w.end >= t]
        if len(keep) != len(self.committed):
            self.committed = keep

    def reset(self, at_time: float = 0.0) -> None:
        """Vacia todo el estado. Se usa tras un seek."""
        self.committed.clear()
        self._previous.clear()
        self._incoming.clear()
        self.last_committed_time = at_time
