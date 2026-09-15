"""Convierte los JSON de jmdict-simplified en una base SQLite para consulta.

El JSON está pensado para procesarse entero, no para buscar una palabra: son
17 MB que habría que recorrer en cada clic. SQLite con los índices adecuados
responde en menos de un milisegundo, que es lo que hace falta para que la
tarjeta de palabra aparezca sin que se note.

    cd backend
    uv run python -m youjp.dict.build_db

Se cargan dos ficheros de glosas. El español de JMdict es una contribución
parcial —cubre bastante menos que el inglés— así que el inglés queda como
respaldo, marcado como tal para que en pantalla se distinga de una acepción
revisada en español.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import time
from pathlib import Path

from youjp.config import get_settings

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode = WAL;

DROP TABLE IF EXISTS entries;
DROP TABLE IF EXISTS forms;
DROP TABLE IF EXISTS senses;
DROP TABLE IF EXISTS glosses;
DROP TABLE IF EXISTS kanji;
DROP TABLE IF EXISTS meta;

CREATE TABLE entries (
    id        INTEGER PRIMARY KEY,
    common    INTEGER NOT NULL DEFAULT 0,
    freq_rank INTEGER          -- 1..48 desde las etiquetas nf01..nf48; NULL si no tiene
);

CREATE TABLE forms (
    entry_id INTEGER NOT NULL,
    text     TEXT    NOT NULL,
    is_kana  INTEGER NOT NULL,
    common   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE senses (
    entry_id  INTEGER NOT NULL,
    sense_idx INTEGER NOT NULL,
    pos       TEXT,   -- JSON: ["n", "vs"]
    misc      TEXT,
    field     TEXT,
    info      TEXT
);

CREATE TABLE glosses (
    entry_id  INTEGER NOT NULL,
    sense_idx INTEGER NOT NULL,
    lang      TEXT    NOT NULL,
    text      TEXT    NOT NULL
);

CREATE TABLE kanji (
    literal   TEXT PRIMARY KEY,
    grade     INTEGER,
    strokes   INTEGER,
    frequency INTEGER,
    on_yomi   TEXT,
    kun_yomi  TEXT,
    meanings  TEXT
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

INDEXES = """
CREATE INDEX idx_forms_text   ON forms(text);
CREATE INDEX idx_forms_entry  ON forms(entry_id);
CREATE INDEX idx_senses_entry ON senses(entry_id, sense_idx);
CREATE INDEX idx_glosses      ON glosses(entry_id, lang, sense_idx);
"""

_NF = re.compile(r"^nf(\d{2})$")


def _freq_rank(tags: list[str]) -> int | None:
    """Extrae el rango de frecuencia de las etiquetas de JMdict.

    ``nf01`` es el grupo de las 500 palabras más frecuentes, ``nf48`` el de las
    menos. Es el dato de frecuencia más fiable que viene en JMdict, y mejor
    señal que el nivel JLPT para decidir qué resaltar: el JLPT no publica listas
    oficiales desde 2010.
    """
    for tag in tags:
        if match := _NF.match(tag):
            return int(match.group(1))
    return None


def _load_words(path: Path) -> tuple[str, list[dict]]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    langs = ",".join(data.get("languages", []))
    return langs, data["words"]


def build(
    conn: sqlite3.Connection, spa_path: Path, eng_path: Path, kanjidic_path: Path | None
) -> dict[str, int]:
    conn.executescript(SCHEMA)
    stats = {"entries": 0, "forms": 0, "senses": 0, "glosses_spa": 0, "glosses_eng": 0}

    # --- entradas, formas y sentidos, desde el fichero en inglés -----------
    # El esqueleto se construye con el inglés y no con el español a propósito.
    # El español de JMdict cubre unas 34 000 entradas de las más de 200 000 del
    # diccionario: construyéndolo al revés, cualquier palabra sin traducción al
    # español se quedaría sin entrada, sin lectura y sin categoría — es decir,
    # sin tarjeta. Con el inglés de base, esas palabras siguen siendo
    # consultables y solo pierden la glosa en español.
    lang, words = _load_words(eng_path)
    log.info("jmdict-eng: %d entradas (%s)", len(words), lang)

    entries, forms, senses, glosses = [], [], [], []
    for word in words:
        entry_id = int(word["id"])
        best_rank: int | None = None
        is_common = False

        for kind, is_kana in (("kanji", 0), ("kana", 1)):
            for form in word.get(kind, []):
                tags = form.get("tags", [])
                rank = _freq_rank(tags)
                if rank is not None and (best_rank is None or rank < best_rank):
                    best_rank = rank
                common = 1 if form.get("common") else 0
                is_common = is_common or bool(common)
                forms.append((entry_id, form["text"], is_kana, common))

        entries.append((entry_id, 1 if is_common else 0, best_rank))

        for idx, sense in enumerate(word.get("sense", [])):
            senses.append(
                (
                    entry_id,
                    idx,
                    json.dumps(sense.get("partOfSpeech", []), ensure_ascii=False),
                    json.dumps(sense.get("misc", []), ensure_ascii=False),
                    json.dumps(sense.get("field", []), ensure_ascii=False),
                    json.dumps(sense.get("info", []), ensure_ascii=False),
                )
            )
            for gloss in sense.get("gloss", []):
                glosses.append((entry_id, idx, "eng", gloss["text"]))

    conn.executemany("INSERT OR IGNORE INTO entries VALUES (?,?,?)", entries)
    conn.executemany("INSERT INTO forms VALUES (?,?,?,?)", forms)
    conn.executemany("INSERT INTO senses VALUES (?,?,?,?,?,?)", senses)
    conn.executemany("INSERT INTO glosses VALUES (?,?,?,?)", glosses)
    stats.update(
        entries=len(entries), forms=len(forms), senses=len(senses), glosses_eng=len(glosses)
    )

    # --- glosas en español, encima de las entradas que ya existen ----------
    # Los identificadores de JMdict son los mismos en los dos ficheros, así que
    # basta con añadir las glosas donde las haya.
    _, spa_words = _load_words(spa_path)
    known = {row[0] for row in conn.execute("SELECT id FROM entries")}
    spa_glosses = []
    con_espanol = set()
    for word in spa_words:
        entry_id = int(word["id"])
        if entry_id not in known:
            continue
        for idx, sense in enumerate(word.get("sense", [])):
            for gloss in sense.get("gloss", []):
                spa_glosses.append((entry_id, idx, "spa", gloss["text"]))
                con_espanol.add(entry_id)
    conn.executemany("INSERT INTO glosses VALUES (?,?,?,?)", spa_glosses)
    stats["glosses_spa"] = len(spa_glosses)
    stats["entries_con_es"] = len(con_espanol)
    log.info(
        "cobertura en español: %d de %d entradas (%.0f %%)",
        len(con_espanol),
        len(entries),
        100 * len(con_espanol) / max(1, len(entries)),
    )

    # --- kanji -------------------------------------------------------------
    if kanjidic_path and kanjidic_path.is_file():
        with kanjidic_path.open(encoding="utf-8") as handle:
            kanjidic = json.load(handle)
        rows = []
        for char in kanjidic.get("characters", []):
            misc = char.get("misc", {})
            on_yomi, kun_yomi, meanings = [], [], []
            for group in char.get("readingMeaning", {}).get("groups", []):
                for reading in group.get("readings", []):
                    if reading["type"] == "ja_on":
                        on_yomi.append(reading["value"])
                    elif reading["type"] == "ja_kun":
                        kun_yomi.append(reading["value"])
                for meaning in group.get("meanings", []):
                    if meaning.get("lang") in ("es", "en"):
                        meanings.append(f"{meaning['lang']}:{meaning['value']}")
            strokes = misc.get("strokeCounts") or []
            rows.append(
                (
                    char["literal"],
                    misc.get("grade"),
                    strokes[0] if strokes else None,
                    misc.get("frequency"),
                    "、".join(on_yomi),
                    "、".join(kun_yomi),
                    "; ".join(meanings),
                )
            )
        conn.executemany("INSERT OR REPLACE INTO kanji VALUES (?,?,?,?,?,?,?)", rows)
        stats["kanji"] = len(rows)

    conn.executescript(INDEXES)
    conn.executemany(
        "INSERT OR REPLACE INTO meta VALUES (?,?)",
        [(k, str(v)) for k, v in stats.items()],
    )
    conn.commit()
    conn.execute("ANALYZE")
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=settings.data_dir / "raw")
    parser.add_argument("--out", type=Path, default=settings.dict_db)
    args = parser.parse_args()

    spa = args.raw / "jmdict-spa.json"
    eng = args.raw / "jmdict-eng.json"
    kanjidic = args.raw / "kanjidic2.json"

    for required in (spa, eng):
        if not required.is_file():
            print(f"falta {required}. Ejecuta: uv run python ../scripts/fetch_dicts.py")
            return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.unlink(missing_ok=True)

    t0 = time.perf_counter()
    conn = sqlite3.connect(args.out)
    try:
        stats = build(conn, spa, eng, kanjidic)
    finally:
        conn.close()

    size_mb = args.out.stat().st_size / 1024**2
    print(f"\n{args.out}  ({size_mb:.1f} MB, {time.perf_counter() - t0:.1f} s)")
    for key, value in stats.items():
        print(f"  {key:<14} {value:>9,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
