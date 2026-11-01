from sqlalchemy.orm import Session

from app.models import Dataset

BARS = {"id": "r2", "kind": "bars", "title": "R²", "unit": "R²", "categories": ["A", "B"],
        "series": [{"name": "статья", "values": [0.7, 0.2]}, {"name": "повтор", "values": [0.0, 0.1]}]}


def test_code_is_assigned_automatically(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    a = c.post("/api/experiments", json={"title": "первый"}).json()["code"]
    b = c.post("/api/experiments", json={"title": "второй"}).json()["code"]
    assert (a, b) == ("EXP-001", "EXP-002")


def test_report_is_saved_and_validated(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    code = c.post("/api/experiments", json={"title": "с отчётом"}).json()["code"]
    report = {"kpis": [{"label": "R²", "value": "0,03"}], "charts": [BARS],
              "analysis": {"summary": "не воспроизводится", "why": ["подбор по тесту"]}}
    r = c.patch(f"/api/experiments/{code}", json={"report": report})
    assert r.status_code == 200, r.text
    assert r.json()["report"]["charts"][0]["id"] == "r2"
    broken = {**BARS, "series": [{"name": "x", "values": [1.0]}]}  # значений меньше категорий
    assert c.patch(f"/api/experiments/{code}", json={"report": {"charts": [broken]}}).status_code == 422
    bad_range = {"id": "s", "kind": "ranges", "title": "t", "rows": [{"name": "a", "mean": 5, "min": 0, "max": 1}]}
    assert c.patch(f"/api/experiments/{code}", json={"report": {"charts": [bad_range]}}).status_code == 422


def test_run_report_merges_into_experiment(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    db_session.add(Dataset(code="DS-09", title="t", access_level="public"))
    db_session.commit()
    c = make_client("res", "researcher")
    code = c.post("/api/experiments", json={"title": "с запуском"}).json()["code"]
    c.patch(f"/api/experiments/{code}", json={"report": {"analysis": {"summary": "написано людьми"}}})
    run = {"runner_commit": "abc1234", "dataset": {"code": "DS-09", "sha256": "c" * 64},
           "env_lock_sha256": "d" * 64, "seeds": {"split": 1}, "parts": {"p": {"exit_code": 0}},
           "report": {"charts": [BARS], "analysis": {"summary": "из расчёта"}}}
    assert c.post(f"/api/experiments/{code}/runs", json=run).status_code == 201
    rep = c.get(f"/api/experiments/{code}").json()["report"]
    assert rep["charts"][0]["id"] == "r2"
    assert rep["analysis"]["summary"] == "написано людьми"  # разбор людей не затирается
