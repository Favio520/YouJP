"""Consulta del diccionario.

Todo lo que sale de aquí es determinista y verificable: viene de JMdict, no de un
modelo. Esa es la línea que separa lo que se puede mostrar como un hecho —
lectura, forma de diccionario, categoría, acepciones— de lo que hay que marcar
como generado.

Una consulta tarda menos de un milisegundo, así que la tarjeta de palabra puede
aparecer en el mismo fotograma del clic.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Correspondencia gruesa entre las categorías de Sudachi y las etiquetas de
# JMdict. Solo sirve para desempatar entre entradas homógrafas: 開く es v5k
# (abrirse) y v1 (abrir), y saber que Sudachi lo ha analizado como verbo evita
# ofrecer la entrada de sustantivo.
_POS_HINTS: dict[str, tuple[str, ...]] = {
    "名詞": ("n", "n-suf", "n-pref", "pn", "adj-na"),
    "動詞": ("v1", "v5", "vs", "vk", "vz", "vi", "vt"),
    "形容詞": ("adj-i",),
    "形状詞": ("adj-na",),
    "副詞": ("adv", "adv-to"),
    "連体詞": ("adj-pn",),
    "接続詞": ("conj",),
    "感動詞": ("int",),
    "代名詞": ("pn",),
}


@dataclass(slots=True)
class Sense:
    pos: list[str] = field(default_factory=list)
    misc: list[str] = field(default_factory=list)
    glosses_es: list[str] = field(default_factory=list)
    glosses_en: list[str] = field(default_factory=list)

    @property
    def has_spanish(self) -> bool:
        return bool(self.glosses_es)


@dataclass(slots=True)
class DictEntry:
    id: int
    kanji_forms: list[str]
    kana_forms: list[str]
    common: bool
    freq_rank: int | None
    senses: list[Sense]

    @property
    def has_spanish(self) -> bool:
        return any(s.has_spanish for s in self.senses)

    @property
    def headword(self) -> str:
        return self.kanji_forms[0] if self.kanji_forms else (self.kana_forms[0] if self.kana_forms else "")


@dataclass(slots=True)
class KanjiInfo:
    literal: str
    grade: int | None
    strokes: int | None
    frequency: int | None
    on_yomi: list[str]
    kun_yomi: list[str]
    meanings: list[str]


class Dictionary:
    """Acceso de solo lectura a la base construida por :mod:`build_db`.

    Una conexión por hilo: los objetos de sqlite3 no se pueden compartir entre
    hilos, y el pipeline consulta desde el hilo de NLP mientras el servidor
    puede hacerlo desde el suyo.
    """

    def __init__(self, path: Path, *, max_senses: int = 4) -> None:
        self.path = Path(path)
        self.max_senses = max_senses
        self._local = threading.local()
        if not self.path.is_file():
            raise FileNotFoundError(
                f"no encuentro el diccionario en {self.path}. Constrúyelo con:\n"
                "  uv run python ../scripts/fetch_dicts.py\n"
                "  uv run python -m youjp.dict.build_db"
            )

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    # -- búsqueda ----------------------------------------------------------

    _CANDIDATES_SQL = """
        SELECT e.id, e.common, e.freq_rank,
               EXISTS(SELECT 1 FROM forms f2
                      WHERE f2.entry_id = e.id AND f2.is_kana = 1 AND f2.text = ?) AS reading_match,
               EXISTS(SELECT 1 FROM glosses g
                      WHERE g.entry_id = e.id AND g.lang = 'spa')                  AS has_es
        FROM forms f JOIN entries e ON e.id = f.entry_id
        WHERE f.text = ?
        GROUP BY e.id
        ORDER BY reading_match DESC, e.common DESC, has_es DESC,
                 COALESCE(e.freq_rank, 99), e.id
        LIMIT 12
    """

    @staticmethod
    def _normalize_reading(reading: str) -> str:
        """Sudachi devuelve las lecturas en katakana; JMdict las guarda en
        hiragana.

        Sin esta conversión el desempate por lectura no falla: simplemente nunca
        acierta, y 開く devuelve la misma entrada tanto si Sudachi lo ha leído
        como ヒラク o como アク. Un fallo silencioso que solo se ve comparando
        dos consultas que deberían dar resultados distintos.
        """
        from youjp.nlp.romaji import katakana_to_hiragana

        return katakana_to_hiragana(reading) if reading else ""

    def candidates(self, text: str, reading: str = "") -> list[sqlite3.Row]:
        """Entradas que tienen ``text`` como alguna de sus formas, ya ordenadas.

        La puntuación se resuelve dentro de la consulta a propósito. La versión
        anterior cargaba las doce candidatas enteras —tres consultas cada una—
        solo para elegir una: 13,7 ms por búsqueda, cuando una frase de quince
        palabras necesita treinta. Aquí se decide con una sola consulta y solo se
        carga la ganadora.

        El orden de desempate: coincide la lectura, luego marcada como común en
        JMdict, luego tiene español, luego frecuencia. Para una palabra
        homógrafa, la acepción común es casi siempre la que se busca.
        """
        return list(
            self._conn.execute(self._CANDIDATES_SQL, (self._normalize_reading(reading), text))
        )

    def lookup(
        self, text: str, *, reading: str = "", sudachi_pos: str = ""
    ) -> DictEntry | None:
        """Busca una palabra y devuelve la entrada más probable.

        ``reading`` y ``sudachi_pos`` solo desempatan; no son obligatorios.
        """
        rows = self.candidates(text, reading)
        if not rows:
            return None

        hints = _POS_HINTS.get(sudachi_pos, ())
        if not hints or len(rows) == 1:
            row = rows[0]
            return self._load_entry(row["id"], bool(row["common"]), row["freq_rank"])

        # Con varias candidatas y una pista de categoría, se comprueba solo esa
        # pista contra la tabla de sentidos, sin cargar las entradas.
        patterns = [f'%"{hint}%' for hint in hints]
        placeholders = " OR ".join(["s.pos LIKE ?"] * len(patterns))
        for row in rows[:4]:
            matches = self._conn.execute(
                f"SELECT 1 FROM senses s WHERE s.entry_id = ? AND ({placeholders}) LIMIT 1",
                (row["id"], *patterns),
            ).fetchone()
            if matches:
                return self._load_entry(row["id"], bool(row["common"]), row["freq_rank"])

        row = rows[0]
        return self._load_entry(row["id"], bool(row["common"]), row["freq_rank"])

    def lookup_all(self, text: str, limit: int = 5) -> list[DictEntry]:
        """Todas las entradas homógrafas, para cuando el estudiante quiere ver
        las otras lecturas posibles."""
        return [
            self._load_entry(row["id"], bool(row["common"]), row["freq_rank"])
            for row in self.candidates(text)[:limit]
        ]

    def _load_entry(self, entry_id: int, common: bool, freq_rank: int | None) -> DictEntry:
        kanji_forms, kana_forms = [], []
        for row in self._conn.execute(
            "SELECT text, is_kana FROM forms WHERE entry_id = ?", (entry_id,)
        ):
            (kana_forms if row["is_kana"] else kanji_forms).append(row["text"])

        senses: dict[int, Sense] = {}
        for row in self._conn.execute(
            "SELECT sense_idx, pos, misc FROM senses WHERE entry_id = ? ORDER BY sense_idx",
            (entry_id,),
        ):
            senses[row["sense_idx"]] = Sense(
                pos=json.loads(row["pos"] or "[]"), misc=json.loads(row["misc"] or "[]")
            )

        for row in self._conn.execute(
            "SELECT sense_idx, lang, text FROM glosses WHERE entry_id = ? ORDER BY sense_idx",
            (entry_id,),
        ):
            sense = senses.setdefault(row["sense_idx"], Sense())
            target = sense.glosses_es if row["lang"] == "spa" else sense.glosses_en
            target.append(row["text"])

        ordered = [senses[k] for k in sorted(senses)]
        # Las acepciones con español primero: son las revisadas y las que se
        # pueden mostrar sin advertencia.
        ordered.sort(key=lambda s: 0 if s.has_spanish else 1)

        return DictEntry(
            id=entry_id,
            kanji_forms=kanji_forms,
            kana_forms=kana_forms,
            common=common,
            freq_rank=freq_rank,
            senses=ordered[: self.max_senses],
        )

    # -- kanji -------------------------------------------------------------

    def kanji(self, literal: str) -> KanjiInfo | None:
        row = self._conn.execute(
            "SELECT * FROM kanji WHERE literal = ?", (literal,)
        ).fetchone()
        if row is None:
            return None
        return KanjiInfo(
            literal=row["literal"],
            grade=row["grade"],
            strokes=row["strokes"],
            frequency=row["frequency"],
            on_yomi=[r for r in (row["on_yomi"] or "").split("、") if r],
            kun_yomi=[r for r in (row["kun_yomi"] or "").split("、") if r],
            meanings=[m for m in (row["meanings"] or "").split("; ") if m],
        )

    def stats(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self._conn.execute("SELECT * FROM meta")}
