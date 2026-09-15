"""Agrupa morfemas en unidades con sentido para el estudiante.

Sudachi no devuelve cadenas de conjugación: devuelve morfemas sueltos con su
categoría y su forma. ``食べさせられました`` sale como cinco piezas
independientes, y mostrarlas así obligaría al estudiante a recomponer mentalmente
lo que precisamente está intentando aprender.

Este módulo las vuelve a pegar: una palabra de contenido con los auxiliares que
la siguen, más la lista de operaciones que se le han aplicado. Es un análisis de
文節 recortado — no hace falta un parser de dependencias completo para esto.

    食べ + させ + られ + まし + た
      -> 食べる [causativo, pasivo, formal, pasado]

Lo que **no** se pega son las partículas de caso (は, が, を) ni las temáticas:
son marcas gramaticales independientes que el estudiante debe ver por separado.
Sí se pegan las partículas conjuntivas (て, ば), que forman parte de la forma
verbal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from youjp.nlp.tokenizer import Morpheme

# --- categorías que se adhieren a la palabra anterior ----------------------

AUX_POS = "助動詞"  # 助動詞, auxiliar
PARTICLE_POS = "助詞"  # 助詞
CONJUNCTIVE_PARTICLE = "接続助詞"  # 接続助詞: て, ば, と...
SUFFIX_POS = "接尾辞"  # 接尾辞
DEPENDENT = "非自立可能"  # 非自立可能: いる, くる, しまう...

# --- etiquetas de la cadena -----------------------------------------------

AUX_LABELS: dict[str, str] = {
    "せる": "causativo",
    "させる": "causativo",
    "ます": "formal",
    "です": "formal",
    "た": "pasado",
    "ない": "negativo",
    "ぬ": "negativo",
    "ず": "negativo",
    "たい": "deseo",
    "らしい": "al parecer",
    "ようだ": "parece que",
    "そうだ": "aparentemente",
    "べきだ": "deber",
    "だ": "afirmativo",
}

DEPENDENT_LABELS: dict[str, str] = {
    "いる": "progresivo",
    "ある": "resultativo",
    "しまう": "completivo",
    "おく": "preparatorio",
    "みる": "tentativo",
    "くる": "acercamiento",
    "いく": "alejamiento",
    "くれる": "favor recibido",
    "あげる": "favor dado",
    "もらう": "favor solicitado",
}

PARTICLE_LABELS: dict[str, str] = {
    "ば": "condicional",
    "たら": "condicional",
    "ながら": "simultáneo",
}

# れる/られる no tiene una lectura única: es pasivo, potencial o respetuoso según
# el contexto, y ninguna regla morfológica lo distingue. Se etiqueta como
# ambiguo en vez de elegir por el estudiante; desambiguarlo es un buen caso de
# uso del botón de IA.
AMBIGUOUS_PASSIVE = {"れる", "られる"}
AMBIGUOUS_LABEL = "pasivo / potencial / respetuoso"


@dataclass(slots=True)
class Chunk:
    """Una palabra de contenido con sus auxiliares."""

    surface: str
    lemma: str
    """Forma de diccionario de la palabra de contenido, no del último auxiliar."""

    normalized: str
    reading: str
    pos: tuple[str, ...]
    begin: int
    end: int
    morphemes: list[Morpheme] = field(default_factory=list)
    chain: list[str] = field(default_factory=list)
    """Operaciones aplicadas, en orden de aplicación."""

    @property
    def is_content(self) -> bool:
        return bool(self.pos) and self.pos[0] not in (PARTICLE_POS, AUX_POS)

    @property
    def is_conjugated(self) -> bool:
        return bool(self.chain)


def _attaches(previous: Chunk | None, morpheme: Morpheme) -> bool:
    """Si este morfema continúa la palabra anterior en vez de empezar una nueva."""
    if previous is None or not previous.is_content:
        return False
    if morpheme.pos0 == AUX_POS:
        return True
    if morpheme.pos0 == PARTICLE_POS and morpheme.pos1 == CONJUNCTIVE_PARTICLE:
        return True
    if morpheme.pos0 == SUFFIX_POS:
        return True
    # いる en 食べている: verbo marcado como dependiente.
    return DEPENDENT in morpheme.pos and morpheme.pos0 == "動詞"


def _label(morpheme: Morpheme) -> str | None:
    base = morpheme.dictionary_form
    if base in AMBIGUOUS_PASSIVE:
        return AMBIGUOUS_LABEL
    if morpheme.pos0 == AUX_POS:
        return AUX_LABELS.get(base)
    if morpheme.pos0 == PARTICLE_POS:
        return PARTICLE_LABELS.get(base)
    if DEPENDENT in morpheme.pos:
        return DEPENDENT_LABELS.get(base)
    if morpheme.pos0 == SUFFIX_POS:
        return None
    return None


def chunk(morphemes: list[Morpheme]) -> list[Chunk]:
    """Agrupa una lista de morfemas en fragmentos."""
    chunks: list[Chunk] = []

    for morpheme in morphemes:
        previous = chunks[-1] if chunks else None

        if _attaches(previous, morpheme):
            assert previous is not None
            previous.surface += morpheme.surface
            previous.end = morpheme.end
            previous.morphemes.append(morpheme)
            if (label := _label(morpheme)) and label not in previous.chain:
                previous.chain.append(label)
            continue

        chunks.append(
            Chunk(
                surface=morpheme.surface,
                lemma=morpheme.dictionary_form,
                normalized=morpheme.normalized_form,
                reading=morpheme.reading,
                pos=morpheme.pos,
                begin=morpheme.begin,
                end=morpheme.end,
                morphemes=[morpheme],
            )
        )

    return chunks
