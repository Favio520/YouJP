"""Hilo de análisis morfológico y consulta de diccionario.

Va en paralelo al traductor, no detrás de él: son dos trabajos independientes
sobre la misma frase, y encadenarlos sumaría sus latencias sin ganar nada. El
japonés sale primero, y tokens y traducción llegan cada uno cuando está.

Todo lo que produce este hilo es determinista. Ni una llamada a un modelo
generativo: lectura, forma de diccionario, categoría y acepciones salen de
Sudachi y de JMdict, que es lo que permite mostrarlas como hechos.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from pydantic import BaseModel

from youjp.config import Settings
from youjp.dict.jmdict import DictEntry, Dictionary
from youjp.nlp.chunker import Chunk, chunk
from youjp.nlp.labels import pos_label
from youjp.nlp.romaji import reading_forms
from youjp.nlp.tokenizer import JapaneseTokenizer
from youjp.obs.metrics import MetricsCollector
from youjp.ws.protocol import DictPayload, NlpTokens, SensePayload, Token

log = logging.getLogger(__name__)

_STOP = object()

# Categorías sin tarjeta propia. Se pintan, pero no se pueden pulsar: una
# partícula no tiene "significado" que enseñar fuera de su función gramatical,
# y ofrecer una tarjeta para は llena la interfaz de ruido.
NON_CLICKABLE = frozenset(
    {"助詞", "助動詞", "補助記号", "空白"}
)


def _to_payload(entry: DictEntry) -> DictPayload:
    return DictPayload(
        id=entry.id,
        headword=entry.headword,
        readings=entry.kana_forms[:4],
        common=entry.common,
        freq_rank=entry.freq_rank,
        senses=[
            SensePayload(pos=s.pos, glosses_es=s.glosses_es[:6], glosses_en=s.glosses_en[:4])
            for s in entry.senses
        ],
    )


class SentenceAnalyzer:
    """Convierte una frase en tokens con su información de diccionario."""

    def __init__(self, tokenizer: JapaneseTokenizer, dictionary: Dictionary | None) -> None:
        self.tokenizer = tokenizer
        self.dictionary = dictionary

    def analyze(self, text: str) -> list[Token]:
        tokens: list[Token] = []
        for i, piece in enumerate(chunk(self.tokenizer.tokenize(text, mode="C"))):
            tokens.append(self._token(i, piece))
        return tokens

    def _token(self, index: int, piece: Chunk) -> Token:
        kana, romaji = reading_forms(piece.reading)
        clickable = bool(piece.pos) and piece.pos[0] not in NON_CLICKABLE

        entry = None
        if clickable and self.dictionary is not None:
            # Se prueba primero la forma normalizada, que unifica variantes
            # ortográficas, y luego la de diccionario. Para 食べさせられました,
            # las dos apuntan a 食べる.
            entry = self.dictionary.lookup(
                piece.normalized, reading=piece.reading, sudachi_pos=piece.pos[0]
            )
            if entry is None and piece.lemma != piece.normalized:
                entry = self.dictionary.lookup(
                    piece.lemma, reading=piece.reading, sudachi_pos=piece.pos[0]
                )

        return Token(
            i=index,
            span=(piece.begin, piece.end),
            surface=piece.surface,
            lemma=piece.lemma,
            kana=kana,
            romaji=romaji,
            pos=list(piece.pos[:3]),
            pos_label=pos_label(piece.pos),
            chain=piece.chain,
            # Sin entrada no hay nada que enseñar al pulsar.
            clickable=clickable and entry is not None,
            entry=_to_payload(entry) if entry else None,
        )


class NlpWorker:
    def __init__(
        self,
        settings: Settings,
        analyzer: SentenceAnalyzer,
        emit: Callable[[BaseModel], None],
        *,
        metrics: MetricsCollector | None = None,
        max_queued: int = 32,
    ) -> None:
        self.settings = settings
        self.analyzer = analyzer
        self.metrics = metrics or MetricsCollector()
        self._emit = emit
        self._queue: queue.Queue = queue.Queue(maxsize=max_queued)
        self._dropped = 0
        self._thread = threading.Thread(target=self._run, name="nlp-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)

    def submit(self, segment_id: int, text: str) -> None:
        try:
            self._queue.put_nowait((segment_id, text))
        except queue.Full:
            self._dropped += 1
            self.metrics.count("dropped_analyses")

    def _run(self) -> None:
        log.info("hilo de analisis arrancado")
        # La conexión a SQLite es por hilo, así que este tiene la suya y su
        # propia caché fría. Calentarla aquí y no en la primera frase evita que
        # el arranque de cada sesión se analice cien veces más despacio.
        if self.analyzer.dictionary is not None:
            ms = self.analyzer.dictionary.warmup()
            log.debug("diccionario calentado en el hilo de analisis: %.0f ms", ms)
        while True:
            item = self._queue.get()
            if item is _STOP:
                break
            segment_id, text = item
            try:
                t0 = time.perf_counter()
                tokens = self.analyzer.analyze(text)
                ms = (time.perf_counter() - t0) * 1000
                self.metrics.record("nlp_ms", ms)
                self._emit(
                    NlpTokens(segment_id=segment_id, tokens=tokens, analysis_ms=round(ms, 2))
                )
            except Exception:  # noqa: BLE001 - un fallo no debe matar el hilo
                log.exception("error analizando el segmento %d", segment_id)
        log.info("hilo de analisis terminado (%d descartados)", self._dropped)

    @property
    def dropped(self) -> int:
        return self._dropped
