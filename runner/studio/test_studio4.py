"""Студия, этап 4: переменные, управление (условие, ссылка, подмодель, цикл), узел Python, куб.
Данные — заглушки."""

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import engine, pycheck, stats  # noqa: E402


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({"отрасль": ["A", "A", "B", "B", "B"], "год": [2020, 2021, 2020, 2021, 2021],
                         "выручка": [10.0, 12.0, 5.0, 7.0, 9.0]})


def N(i: str, t: str, **params: Any) -> dict[str, Any]:
    return {"id": i, "type": t, "params": params}


def E(a: str, b: str, port: str = "in") -> dict[str, str]:
    return {"from": a, "to": b, "port": port}


def sc(*nodes: dict[str, Any], edges: list[dict[str, str]], variables: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"format": 1, "nodes": list(nodes), "edges": edges, "variables": variables or []}


def ok(res: dict[str, engine.NodeResult], node: str) -> pd.DataFrame:
    r = res[node]
    assert r.frame is not None, r.error
    return r.frame


def test_variables(df: pd.DataFrame) -> None:
    g = sc(N("src", "import.dataset", snapshot_id=1),
           N("f", "transform.filter", expr="год = $год"),
           N("mx", "transform.group", keys=[], aggregations=[{"column": "выручка", "func": "max", "as": "максимум"}]),
           N("tv", "vars.from_table", columns=["максимум"]),
           N("vc", "vars.calc", fields=[{"name": "порог", "expr": "$максимум / 2"}]),
           N("join", "vars.join", prefer="second"),
           N("calc", "transform.calculator", fields=[{"name": "доля", "expr": "выручка / $максимум"},
                                                     {"name": "выше", "expr": "выручка > $порог"}]),
           N("rep", "vars.replace", variable="год", rules=[{"find": "2021", "to": "прошлый"}]),
           N("tt", "vars.to_table"),
           edges=[E("src", "f"), E("f", "mx"), E("mx", "tv"), E("tv", "vc"), E("f", "join"), E("vc", "join", "in2"),
                  E("join", "calc"), E("calc", "rep"), E("rep", "tt")],
           variables=[{"name": "год", "value": "2021"}])
    res = engine.run(g, lambda _n: df)
    calc = ok(res, "calc")
    assert calc["доля"].tolist() == pytest.approx([1.0, 7 / 12, 0.75]) and calc["выше"].tolist() == [True, True, True]
    table = dict(zip(ok(res, "tt")["переменная"], ok(res, "tt")["значение"], strict=True))
    assert table["год"] == "прошлый" and table["порог"] == "6.0" and table["максимум"] == "12.0"
    bad = engine.run(sc(N("src", "import.dataset", snapshot_id=1), N("f", "transform.filter", expr="год = $нет"),
                        edges=[E("src", "f")]), lambda _n: df)
    assert "Нет переменной $нет" in bad["f"].error


def test_condition_ref_and_exec(df: pd.DataFrame) -> None:
    g = sc(N("src", "import.dataset", snapshot_id=1),
           N("yes", "control.condition", expr="$СТРОК > 3"),
           N("no", "control.condition", expr="$СТРОК > 100"),
           N("stop", "control.condition", expr="$СТРОК > 100", otherwise="stop"),
           N("ref", "control.ref", node="yes"),
           N("ex", "control.exec", after=["no"]),
           edges=[E("src", "yes"), E("src", "no"), E("src", "stop"), E("src", "ex")])
    res = engine.run(g, lambda _n: df)
    assert len(ok(res, "yes")) == 5 and len(ok(res, "no")) == 0 and list(ok(res, "no").columns) == list(df.columns)
    assert "не выполнено" in res["stop"].error
    assert len(ok(res, "ref")) == 5
    p = engine.plan(g)
    assert p.order.index("no") < p.order.index("ex") and p.order.index("yes") < p.order.index("ref")
    loop = sc(N("a", "control.ref", node="b"), N("b", "control.ref", node="a"), edges=[])
    with pytest.raises(engine.ScenarioError, match="цикл"):
        engine.plan(loop)
    assert engine.run(g, lambda _n: df, until="ref").keys() == {"src", "yes", "ref"}


SUB = sc(N("i", "control.input", port="in"),
         N("g", "transform.group", keys=["год"], aggregations=[{"column": "выручка", "func": "sum", "as": "итого"}]),
         N("c", "transform.calculator", fields=[{"name": "метка", "expr": 'СЦЕП("цикл "; $ЦИКЛ)'}]),
         N("o", "control.output"),
         edges=[E("i", "g"), E("g", "c"), E("c", "o")], variables=[{"name": "ЦИКЛ", "value": "нет"}])


def test_submodel_and_loop(df: pd.DataFrame) -> None:
    g = sc(N("src", "import.dataset", snapshot_id=1),
           N("sub", "control.submodel", scenario="SC-09", __graph__=SUB),
           N("loop", "control.loop", scenario="SC-09", by="отрасль", __graph__=SUB),
           edges=[E("src", "sub"), E("src", "loop")])
    res = engine.run(g, lambda _n: df)
    sub = ok(res, "sub")
    assert sub["итого"].tolist() == [15.0, 28.0] and sub["метка"].tolist() == ["цикл нет", "цикл нет"]
    lp = ok(res, "loop")
    assert lp.columns.tolist()[0] == "отрасль" and len(lp) == 4
    assert lp[lp["отрасль"] == "B"]["итого"].tolist() == [5.0, 16.0] and set(lp["метка"]) == {"цикл A", "цикл B"}
    # импорт внутри подмодели — данные по id «узел/внутренний узел»
    inner = sc(N("d", "import.dataset", snapshot_id=2), N("o", "control.output"), edges=[E("d", "o")])
    seen: list[str] = []

    def load(n: dict[str, Any]) -> pd.DataFrame:
        seen.append(n["id"])
        return df

    res2 = engine.run(sc(N("s", "control.submodel", scenario="SC-10", __graph__=inner), edges=[]), load)
    assert len(ok(res2, "s")) == 5 and seen == ["s/d"]
    broken = engine.run(sc(N("s", "control.submodel", scenario="SC-10"), edges=[]), load)
    assert "не вложен" in broken["s"].error


def test_python_node(df: pd.DataFrame) -> None:
    code = ("import numpy as np\nout = df.copy()\nout['лог'] = np.log(out['выручка'])\n"
            "vars['итого'] = float(out['выручка'].sum())\nprint('строк', len(out))\n")
    g = sc(N("src", "import.dataset", snapshot_id=1), N("py", "code.python", code=code),
           N("c", "transform.calculator", fields=[{"name": "доля", "expr": "выручка / $итого"}]),
           edges=[E("src", "py"), E("py", "c")])
    res = engine.run(g, lambda _n: df)
    assert "лог" in ok(res, "py").columns and ok(res, "c")["доля"].sum() == pytest.approx(1)
    assert res["py"].report and res["py"].report["notes"] == ["строк 5"]
    for bad, msg in [("import os\nout = df", "«os» не разрешена"), ("out = df.read_csv('x')", "файлы"),
                     ("out = open('x')", "«open» нельзя"), ("out = df.__class__", "служебный атрибут"),
                     ("x = 1/0\nout = df", "строка 1: ZeroDivisionError"), ("y = 1", "положите результат")]:
        r = engine.run(sc(N("src", "import.dataset", snapshot_id=1), N("py", "code.python", code=bad),
                          edges=[E("src", "py")]), lambda _n: df)
        assert msg in r["py"].error, (bad, r["py"].error)
    assert pycheck.check("import pandas as pd\nout = df.groupby('a').sum()") == []
    assert pycheck.sha256("x") == pycheck.sha256("x") != pycheck.sha256("y")


def test_cube(df: pd.DataFrame) -> None:
    c = stats.cube(df.assign(код=range(5)))
    assert c is not None and c["dims"] == ["отрасль", "год"] and c["measures"] == ["выручка"]  # код — не мера
    cells = pd.DataFrame(c["cells"], columns=[*c["dims"], "__n", "выручка|sum", "выручка|cnt", "выручка|min",
                                              "выручка|max"])
    assert cells["выручка|sum"].sum() == df["выручка"].sum() and cells["__n"].sum() == 5
    b21 = cells[(cells["отрасль"] == "B") & (cells["год"] == "2021")].iloc[0]
    assert b21["выручка|sum"] == 16 and b21["выручка|min"] == 7 and b21["__n"] == 2
