"""Análisis morfológico con Sudachi.

Aquí se resuelve, sin LLM y en microsegundos, casi todo lo que pide la tarjeta de
palabra: superficie, forma de diccionario, lectura, categoría gramatical y tipo
y forma de conjugación. Preguntarle esto a un modelo generativo sería más lento,
no determinista y capaz de inventarse una lectura — que es la peor clase de error
posible cuando quien lee todavía no puede detectarlo.

Sudachi ofrece tres modos de segmentación. Se usan dos, y por motivos distintos:

* **Modo C** (unidades largas) para lo que se pinta: ``選挙管理委員会`` se
  muestra como una palabra, que es como la percibe un lector.
* **Modo A** (unidades cortas) para desmontar esa palabra cuando el estudiante
  quiere ver de qué está hecha.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

log = logging.getLogger(__name__)

SplitModeName = Literal["A", "B", "C"]

# Categorías que pueden encabezar un fragmento por sí solas.
CONTENT_POS = frozenset(
    {
        "名詞",  # sustantivo
        "動詞",  # verbo
        "形容詞",  # adjetivo -i
        "形状詞",  # adjetivo -na
        "副詞",  # adverbio
        "連体詞",  # adnominal
        "接続詞",  # conjunción
        "感動詞",  # interjección
        "代名詞",  # pronombre
        "接頭辞",  # prefijo
    }
)

# Categorías sin valor léxico: no merecen tarjeta propia.
FUNCTION_POS = frozenset(
    {
        "助詞",  # partícula
        "助動詞",  # auxiliar
        "補助記号",  # puntuación
        "空白",  # espacio
    }
)


@dataclass(frozen=True, slots=True)
class Morpheme:
    """Un morfema tal y como lo devuelve Sudachi, con índices sobre el texto."""

    surface: str
    dictionary_form: str
    """Forma de diccionario: 食べました -> 食べる."""

    normalized_form: str
    """Forma normalizada. Unifica variantes ortográficas (即ち/則ち -> すなわち)
    y es la que conviene usar para buscar en el diccionario."""

    reading: str
    """Lectura en katakana. Vacía para símbolos y texto latino."""

    pos: tuple[str, ...]
    """Seis campos: cuatro niveles de categoría, tipo de conjugación y forma."""

    begin: int
    end: int

    @property
    def pos0(self) -> str:
        return self.pos[0] if self.pos else ""

    @property
    def pos1(self) -> str:
        return self.pos[1] if len(self.pos) > 1 else ""

    @property
    def inflection_type(self) -> str:
        """活用型: ``下一段-バ行``, ``助動詞-マス``..."""
        return self.pos[4] if len(self.pos) > 4 else ""

    @property
    def inflection_form(self) -> str:
        """活用形: ``連用形-一般``, ``終止形-一般``..."""
        return self.pos[5] if len(self.pos) > 5 else ""

    @property
    def is_content(self) -> bool:
        return self.pos0 in CONTENT_POS

    @property
    def is_function(self) -> bool:
        return self.pos0 in FUNCTION_POS

    @property
    def is_punctuation(self) -> bool:
        return self.pos0 in ("補助記号", "空白")


class JapaneseTokenizer:
    """Envoltorio de Sudachi. Seguro para usar desde un hilo.

    El diccionario se carga una sola vez y se comparte: son unos 100 MB y
    tardaría medio segundo por instancia.
    """

    def __init__(self, dict_type: str = "core") -> None:
        self.dict_type = dict_type
        self._tokenizer = None
        self._modes: dict[str, object] = {}

    def load(self) -> None:
        if self._tokenizer is not None:
            return
        from sudachipy import Dictionary, SplitMode

        log.info("cargando diccionario de Sudachi (%s)...", self.dict_type)
        self._tokenizer = Dictionary(dict=self.dict_type).create()
        self._modes = {"A": SplitMode.A, "B": SplitMode.B, "C": SplitMode.C}

    def tokenize(self, text: str, mode: SplitModeName = "C") -> list[Morpheme]:
        self.load()
        assert self._tokenizer is not None
        if not text:
            return []
        return [
            Morpheme(
                surface=m.surface(),
                dictionary_form=m.dictionary_form(),
                normalized_form=m.normalized_form(),
                reading=m.reading_form(),
                pos=tuple(m.part_of_speech()),
                begin=m.begin(),
                end=m.end(),
            )
            for m in self._tokenizer.tokenize(text, self._modes[mode])
        ]

    def split(self, morpheme: Morpheme, text: str) -> list[Morpheme]:
        """Desmonta una unidad larga en sus partes cortas.

        Para que ``選挙管理委員会`` se pueda mostrar como una palabra y, al
        pulsarla, enseñar de qué está compuesta.
        """
        return self.tokenize(text[morpheme.begin : morpheme.end], mode="A")


@lru_cache(maxsize=1)
def get_tokenizer(dict_type: str = "core") -> JapaneseTokenizer:
    return JapaneseTokenizer(dict_type)
