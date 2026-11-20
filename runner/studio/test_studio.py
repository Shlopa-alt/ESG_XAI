"""Студия: выражения, компоненты трансформации, движок сценариев, запуск. Данные — заглушки."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import engine, stats  # noqa: E402
from studio.components import COMPONENTS, NodeError, catalog  # noqa: E402
from studio.expr import ExprError, column, mask  # noqa: E402


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "компания": ["A", "A", "B", "B", "C"],
        "год": [2020, 2021, 2020, 2021, 2021],
        "выручка": [100.0, 120.0, 50.0, None, 80.0],
        "сотрудники": [10, 12, 5, 5, 0],
        "дата": ["31.12.2020", "31.12.2021", "31.12.2020", "31.12.2021", "30.06.2021"],
        "доля, %": [1.0, 2.0, 3.0, 4.0, 5.0],
    })


def run(type_: str, params: dict, **frames: pd.DataFrame) -> pd.DataFrame:  # type: ignore[type-arg]
    return COMPONENTS[type_].run(frames, params)


# --- выражения ---

def test_expressions(df: pd.DataFrame) -> None:
    per = column("выручка / сотрудники", df)
    assert per.iloc[0] == 10 and pd.isna(per.iloc[4])  # деление на ноль — пусто
    label = column('ЕСЛИ(выручка > 90; "крупная"; "малая")', df)
    assert list(label) == ["крупная", "крупная", "малая", "малая", "малая"]
    assert list(column("`доля, %` * 10", df)) == [10, 20, 30, 40, 50]
    assert list(column("ГОД(дата)", df)) == [2020, 2021, 2020, 2021, 2021]
    assert list(mask("год = 2021 И НЕ ПУСТО(выручка)", df)) == [False, True, False, False, True]
    assert list(mask("компания <> 'A' ИЛИ сотрудники >= 12", df)) == [False, True, True, True, True]
    assert list(column('СЦЕП(компания; "-"; год)', df))[0] == "A-2020"


@pytest.mark.parametrize("bad", ["__import__('os')", "компания.upper()", "выручка[0]",
                                 "(lambda: 1)()", "open('x')", "нет_такого + 1", "1 +"])
def test_expressions_refuse_anything_else(df: pd.DataFrame, bad: str) -> None:
    with pytest.raises(ExprError):
        column(bad, df)


# --- компоненты ---

def test_group_and_ungroup(df: pd.DataFrame) -> None:
    aggs = [{"column": "выручка", "func": "sum"}, {"column": "год", "func": "count", "as": "лет"}]
    g = run("transform.group", {"keys": ["компания"], "aggregations": aggs}, **{"in": df})
    assert g.to_dict("list") == {"компания": ["A", "B", "C"], "выручка_sum": [220.0, 50.0, 80.0],
                                 "лет": [2, 2, 1]}
    total = run("transform.group", {"keys": [], "aggregations": aggs[:1]}, **{"in": df})
    assert total["выручка_sum"].tolist() == [350.0]
    u = run("transform.ungroup", {"keys": ["компания"], "aggregations": aggs[:1]}, **{"in": df})
    assert len(u) == 5 and u["выручка_sum"].tolist() == [220.0, 220.0, 50.0, 50.0, 80.0]


def test_datetime_replace_calculator(df: pd.DataFrame) -> None:
    d = run("transform.datetime", {"column": "дата", "parts": ["year", "quarter", "year_month"]}, **{"in": df})
    assert d["дата_год"].tolist() == [2020, 2021, 2020, 2021, 2021]
    assert d["дата_квартал"].tolist()[-1] == 2 and d["дата_год_месяц"].tolist()[-1] == "2021-06"
    r = run("transform.replace", {"column": "компания", "rules": [{"find": "A", "to": "Альфа"}],
                                  "others_mode": "value", "others": "прочие", "as": "имя"}, **{"in": df})
    assert r["имя"].tolist() == ["Альфа", "Альфа", "прочие", "прочие", "прочие"]
    rx = run("transform.replace", {"column": "дата", "mode": "regex",
                                   "rules": [{"find": r"^\d+\.\d+\.", "to": ""}]}, **{"in": df})
    assert rx["дата"].tolist()[0] == "2020"
    c = run("transform.calculator", {"fields": [{"name": "на_человека", "expr": "выручка / сотрудники"},
                                                {"name": "x2", "expr": "на_человека * 2"}]}, **{"in": df})
    assert c["x2"].tolist()[0] == 20
    with pytest.raises(NodeError, match="на_человека"):
        run("transform.calculator", {"fields": [{"name": "на_человека", "expr": "нет + 1"}]}, **{"in": df})


def test_crosstab_unpivot_window(df: pd.DataFrame) -> None:
    x = run("transform.crosstab", {"rows": ["компания"], "columns_field": "год", "value": "выручка",
                                   "func": "sum"}, **{"in": df})
    assert list(x.columns) == ["компания", "2020", "2021"] and x.loc[0, "2021"] == 120
    m = run("transform.unpivot", {"keep": ["компания", "год"], "columns": ["выручка", "сотрудники"]},
            **{"in": df})
    assert len(m) == 10 and set(m["показатель"]) == {"выручка", "сотрудники"}
    w = run("transform.window", {"columns": ["выручка"], "group_by": ["компания"], "order_by": "год",
                                 "depth": 1, "horizon": 1}, **{"in": df})
    a = w[w["компания"] == "A"]
    assert pd.isna(a["выручка-1"].iloc[0]) and a["выручка-1"].iloc[1] == 100 and a["выручка+1"].iloc[0] == 120


def test_merge_union_join_lookup(df: pd.DataFrame) -> None:
    ref = pd.DataFrame({"код": ["A", "B", "B"], "отрасль": ["энергетика", "банки", "дубль"]})
    lk = run("transform.lookup", {"key": "компания", "ref_key": "код"}, **{"in": df, "ref": ref})
    assert lk["отрасль"].tolist()[:3] == ["энергетика", "энергетика", "банки"] and pd.isna(lk["отрасль"].iloc[4])
    keys = [{"left": "компания", "right": "код"}]
    assert len(run("transform.merge", {"keys": keys, "how": "inner"}, **{"in": df, "in2": ref})) == 6
    anti = run("transform.merge", {"keys": keys, "how": "anti"}, **{"in": df, "in2": ref})
    assert anti["компания"].tolist() == ["C"] and list(anti.columns) == list(df.columns)
    u = run("transform.union", {"columns": "all", "source": "откуда"}, **{"in": df, "in2": ref})
    assert len(u) == 8 and u["откуда"].tolist()[-1] == "2"
    with pytest.raises(NodeError, match="разное число строк"):
        run("transform.join", {}, **{"in": df, "in2": ref})
    j = run("transform.join", {"allow_unequal": True}, **{"in": df, "in2": ref})
    assert j.shape == (5, 8)


def test_fields_sort_filter(df: pd.DataFrame) -> None:
    raw = pd.DataFrame({"x": ["1 200,5", "3", "нет"], "y": ["да", "нет", ""], "z": [1, 2, 3]})
    f = run("transform.fields", {"fields": [{"column": "x", "type": "number", "rename": "сумма"},
                                            {"column": "y", "type": "bool"}, {"column": "z", "drop": True}]},
            **{"in": raw})
    assert list(f.columns) == ["сумма", "y"] and f["сумма"].tolist()[:2] == [1200.5, 3.0]
    assert f["y"].tolist()[:2] == [True, False]
    s = run("transform.sort", {"by": [{"column": "год", "desc": True}, {"column": "выручка"}]}, **{"in": df})
    assert s["компания"].tolist()[0] == "C"
    flt = run("transform.filter", {"conditions": [{"column": "год", "op": "=", "value": "2021"},
                                                  {"column": "выручка", "op": "not_empty"}]}, **{"in": df})
    assert flt["компания"].tolist() == ["A", "C"]
    by_expr = run("transform.filter", {"expr": "сотрудники > 5", "invert": True}, **{"in": df})
    assert len(by_expr) == 3


# --- движок ---

def _scenario(*nodes: dict, edges: list | None = None) -> dict:  # type: ignore[type-arg]
    return {"format": 1, "nodes": list(nodes), "edges": edges or []}


def test_engine_runs_in_order_and_isolates_errors(df: pd.DataFrame) -> None:
    sc = _scenario(
        {"id": "src", "type": "import.dataset", "params": {"snapshot_id": 1}},
        {"id": "calc", "type": "transform.calculator", "params": {"fields": [{"name": "k", "expr": "год - 2000"}]}},
        {"id": "bad", "type": "transform.filter", "params": {"expr": "нет_столбца > 1"}},
        {"id": "after_bad", "type": "transform.sort", "params": {"by": [{"column": "k"}]}},
        {"id": "grp", "type": "transform.group",
         "params": {"keys": ["k"], "aggregations": [{"column": "выручка", "func": "mean"}]}},
        edges=[{"from": "src", "to": "calc"}, {"from": "calc", "to": "bad"},
               {"from": "bad", "to": "after_bad"}, {"from": "calc", "to": "grp"}],
    )
    res = engine.run(sc, lambda _n: df)
    assert res["grp"].frame is not None and res["grp"].frame["k"].tolist() == [20, 21]
    assert "нет_столбца" in res["bad"].error
    assert res["after_bad"].skipped and res["after_bad"].frame is None
    only = engine.run(sc, lambda _n: df, until="calc")
    assert set(only) == {"src", "calc"}


@pytest.mark.parametrize(("sc", "message"), [
    (_scenario({"id": "a", "type": "нет.такого"}), "Неизвестный компонент"),
    (_scenario({"id": "a", "type": "transform.sort", "params": {"by": [{"column": "x"}]}},
               {"id": "b", "type": "transform.sort", "params": {"by": [{"column": "x"}]}},
               edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]), "цикл"),
    (_scenario({"id": "a", "type": "import.dataset", "params": {"snapshot_id": 1}},
               {"id": "b", "type": "transform.sort", "params": {}},
               edges=[{"from": "a", "to": "b", "port": "ref"}]), "нет входа"),
])
def test_engine_rejects_broken_scenarios(sc: dict, message: str) -> None:  # type: ignore[type-arg]
    with pytest.raises(engine.ScenarioError, match=message):
        engine.run(sc, lambda _n: pd.DataFrame())


def test_engine_reports_missing_settings_and_inputs(df: pd.DataFrame) -> None:
    sc = _scenario({"id": "a", "type": "import.dataset", "params": {"snapshot_id": 1}},
                   {"id": "s", "type": "transform.sort", "params": {}},
                   {"id": "m", "type": "transform.merge", "params": {"keys": [{"left": "год"}]}},
                   edges=[{"from": "a", "to": "s"}, {"from": "a", "to": "m"}])
    res = engine.run(sc, lambda _n: df)
    assert "не заполнено «По столбцам»" in res["s"].error
    assert "не подключён вход «Таблица 2»" in res["m"].error


def test_catalog_and_stats(df: pd.DataFrame) -> None:
    cat = {c["type"]: c for c in catalog()}
    assert len([c for c in cat.values() if c["group"] == "Трансформация"]) == 15
    assert cat["transform.merge"]["inputs"][1] == {"name": "in2", "label": "Таблица 2"}
    t = stats.table(df, rows=2)
    assert t["total"] == 5 and len(t["rows"]) == 2 and t["rows"][0][2] == 100.0
    st = {c["name"]: c for c in stats.statistics(df)["columns"]}
    assert st["выручка"]["missing"] == 1 and st["выручка"]["median"] == 90.0
    assert st["компания"]["top"][0] == {"value": "A", "count": 2}
    json.dumps(stats.statistics(df))  # без NaN и numpy-типов


def test_run_scenario_cli(tmp_path: Path, df: pd.DataFrame) -> None:
    from studio import run_scenario

    data = tmp_path / "data.csv"
    df.to_csv(data, index=False, sep=";")
    sc = _scenario({"id": "src", "type": "import.dataset", "params": {"snapshot_id": 1}},
                   {"id": "f", "type": "transform.filter", "params": {"expr": "год = 2021"}},
                   {"id": "out", "type": "export.file", "params": {"name": "итог/2021", "format": "csv"}},
                   edges=[{"from": "src", "to": "f"}, {"from": "f", "to": "out"}])
    (tmp_path / "s.json").write_text(json.dumps(sc), encoding="utf-8")
    (tmp_path / "i.json").write_text(json.dumps({"src": {"path": str(data)}}), encoding="utf-8")
    res = tmp_path / "res"
    code = run_scenario.main([str(res), "--scenario", str(tmp_path / "s.json"), "--inputs", str(tmp_path / "i.json")])
    assert code == 0
    summary = json.loads((res / "summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] and summary["nodes"]["f"]["rows"] == 3 and summary["files"] == ["итог_2021.csv"]
    saved = pd.read_csv(res / "files" / "итог_2021.csv", encoding="utf-8-sig")
    assert saved["компания"].tolist() == ["A", "B", "C"]
    view = json.loads((res / "nodes" / "f.json").read_text(encoding="utf-8"))
    assert view["table"]["total"] == 3 and view["statistics"]["rows"] == 3


def test_catalog_file_is_current() -> None:
    from studio.catalog import dump

    saved = json.loads((Path(__file__).resolve().parent / "catalog.json").read_text(encoding="utf-8"))
    assert saved == json.loads(dump()), "каталог изменился: python studio/catalog.py > studio/catalog.json"
