"""Студия, этап 5: импорт из базы и экспорт в неё (на SQLite), входы и выход веб-сервиса.
Данные — заглушки."""

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import database, engine  # noqa: E402
from studio.components import COMPONENTS, NodeError  # noqa: E402


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE firms (code INTEGER, name TEXT, roe REAL)")
        con.executemany("INSERT INTO firms VALUES (?, ?, ?)", [(1, "a", 0.1), (2, "b", 0.2), (3, "c; d", 0.3)])
    conns = {"DB-01": {"kind": "sqlite", "database": str(path), "allow_write": False},
             "DB-02": {"kind": "sqlite", "database": str(path), "allow_write": True}}
    monkeypatch.setenv("STUDIO_CONNECTIONS", json.dumps(conns))
    monkeypatch.delenv("STUDIO_PREVIEW", raising=False)
    return path


def test_read_only_queries(db: Path) -> None:
    df = database.read("DB-01", "-- комментарий\nSELECT code, roe FROM firms WHERE name <> 'x;y' ORDER BY code;")
    assert df.to_dict("list") == {"code": [1, 2, 3], "roe": [0.1, 0.2, 0.3]}
    limited = database.read("DB-01", "WITH t AS (SELECT * FROM firms) SELECT * FROM t", max_rows=2)
    assert len(limited) == 2 and "первые 2" in limited.attrs["report"]["notes"][0]
    for bad, msg in [("DELETE FROM firms", "только чтение"), ("SELECT 1; DROP TABLE firms", "один запрос"),
                     ("WITH x AS (DELETE FROM firms RETURNING *) SELECT * FROM x", "DELETE"), ("", "пустой")]:
        with pytest.raises(NodeError, match=msg):
            database.read("DB-01", bad)
    with pytest.raises(NodeError, match="no such table"):
        database.read("DB-01", "SELECT * FROM nope")
    with pytest.raises(NodeError, match="реквизиты не получены"):
        database.read("DB-09", "SELECT 1")


def test_export(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exp = COMPONENTS["export.database"].run
    df = pd.DataFrame({"x": [1, 2], "y": ["p", "q"]})
    with pytest.raises(NodeError, match="запись не разрешена"):
        exp({"in": df}, {"connection": "DB-01", "table": "out_t", "mode": "append"})
    with pytest.raises(NodeError, match="имя таблицы"):
        exp({"in": df}, {"connection": "DB-02", "table": "out; drop", "mode": "append"})
    monkeypatch.setenv("STUDIO_PREVIEW", "1")
    exp({"in": df}, {"connection": "DB-02", "table": "out_t", "mode": "append"})
    with sqlite3.connect(db) as con:  # предпросмотр ничего не записал
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name='out_t'").fetchone()[0] == 0
    monkeypatch.delenv("STUDIO_PREVIEW")
    exp({"in": df}, {"connection": "DB-02", "table": "out_t", "mode": "append"})
    exp({"in": df}, {"connection": "DB-02", "table": "out_t", "mode": "append"})
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT count(*) FROM out_t").fetchone()[0] == 4
    exp({"in": df}, {"connection": "DB-02", "table": "out_t", "mode": "replace"})
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT count(*) FROM out_t").fetchone()[0] == 2


def test_service_inputs_and_output(db: Path, tmp_path: Path) -> None:
    from studio import run_scenario

    sc = {"format": 1, "nodes": [
        {"id": "i", "type": "control.input", "params": {"port": "in"}},
        {"id": "d", "type": "import.database", "params": {"connection": "DB-01", "query": "SELECT code, roe FROM firms"}},
        {"id": "m", "type": "transform.merge", "params": {"keys": [{"left": "code", "right": "code"}], "how": "inner"}},
        {"id": "o", "type": "control.output", "params": {}}],
        "edges": [{"from": "i", "to": "m", "port": "in"}, {"from": "d", "to": "m", "port": "in2"},
                  {"from": "m", "to": "o", "port": "in"}]}
    (tmp_path / "s.json").write_text(json.dumps(sc), encoding="utf-8")
    (tmp_path / "i.json").write_text("{}", encoding="utf-8")
    (tmp_path / "inj.json").write_text(json.dumps({"in": [{"code": 2, "вес": 5}, {"code": 3, "вес": 7}]}),
                                       encoding="utf-8")
    res = tmp_path / "res"
    code = run_scenario.main([str(res), "--scenario", str(tmp_path / "s.json"), "--inputs", str(tmp_path / "i.json"),
                              "--inject", str(tmp_path / "inj.json"), "--output"])
    assert code == 0
    out = json.loads((res / "output.json").read_text(encoding="utf-8"))
    assert out["columns"] == ["code", "вес", "roe"] and out["rows"] == [[2, 5, 0.2], [3, 7, 0.3]]


def test_decimal_and_odd_types_become_plain() -> None:
    import uuid
    from decimal import Decimal

    from studio import stats

    df = database._typed(pd.DataFrame({"n": [Decimal("1.50"), None], "u": [uuid.uuid4(), None], "s": ["a", "b"]}))
    assert df["n"].tolist()[0] == 1.5 and df["n"].dtype.kind == "f" and isinstance(df["u"].iloc[0], str)
    json.dumps(stats.table(pd.DataFrame({"d": [Decimal("2.5")]})))


def test_engine_loads_database_through_loader(db: Path) -> None:
    sc = {"format": 1, "nodes": [{"id": "d", "type": "import.database",
                                  "params": {"connection": "DB-01", "query": "SELECT * FROM firms"}}], "edges": []}
    res = engine.run(sc, lambda n: database.read(n["params"]["connection"], n["params"]["query"]))
    assert res["d"].frame is not None and len(res["d"].frame) == 3


@pytest.mark.parametrize("module", ["database", "run_scenario", "mining", "control", "python_node", "preprocess",
                                    "research", "engine", "components", "catalog"])
def test_any_module_can_be_imported_first(module: str) -> None:
    """Исполнитель импортирует модули в своём порядке — циклических импортов быть не должно."""
    import subprocess

    root = Path(__file__).resolve().parent.parent
    code = f"import sys; sys.path[:0] = [{str(root)!r}, {str(root / 'methods')!r}]; import studio.{module}"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
