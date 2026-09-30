"""Conexiones SQLite en rutas válidas con espacios y caracteres URI."""

import sqlite3

import pytest

from youjp.dict.jmdict import Dictionary


def test_dictionary_escapes_path_and_can_reopen_after_close(tmp_path):
    path = tmp_path / "Japanese #1 dictionary.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        connection.execute("INSERT INTO meta VALUES ('entries', '1')")
    dictionary = Dictionary(path)
    assert dictionary.stats() == {"entries": "1"}
    previous = dictionary._conn
    dictionary.close()
    dictionary.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        previous.execute("SELECT 1")
    try:
        assert dictionary.stats() == {"entries": "1"}
        assert dictionary._conn is not previous
    finally:
        dictionary.close()
