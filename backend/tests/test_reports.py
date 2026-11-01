from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Experiment, KbImport, QwenJob
from app.services import qwen_reports

TOKEN = {"X-Qwen-Token": "tok"}
SECTIONS = {"summary": "Гипотеза отклонена: ρ = 0,27 незначим", "verdict": "rejected", "verdict_reason": "интервал задевает ноль",
            "interpretation": ["ρ S&P — MSCI = 0,27"], "meaning": "", "methodology": "", "limitations": ["30 компаний"],
            "next": ["DS-05"]}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok",
                    kb_inbox_dir=str(tmp_path))


@pytest.fixture
def exp(db_session: Session) -> None:
    db_session.add(Experiment(code="EXP-001", title="Рейтинги", status="review", config={}, setup=["шаг"], results=[],
                              limitations=[], reproducibility=[], hypothesis="рейтинги согласованы",
                              report={"kpis": [{"label": "S&P — MSCI", "value": "+0,27", "note": "p = 0,18"}],
                                      "charts": [{"id": "rho", "kind": "bars", "title": "ρ", "categories": ["a"],
                                                  "series": [{"name": "ρ", "values": [0.2665]}]}]}))
    db_session.commit()


def _written(c, settings: Settings) -> dict:  # type: ignore[no-untyped-def,type-arg]
    """Заказать отчёт и вписать текст от имени обработчика Qwen."""
    r = c.post("/api/experiments/EXP-001/reports")
    assert r.status_code == 201, r.text
    assert c.post("/api/experiments/EXP-001/reports").status_code == 409  # Qwen ещё пишет
    assert c.post("/api/qwen/worker/next", headers=TOKEN).json()["kind"] == "report"
    return r.json()


def test_numbers_not_in_facts_are_flagged() -> None:
    facts = {"kpis": [{"value": "+0,27"}], "charts": [{"series": [{"values": [0.2949]}]}]}
    assert qwen_reports.check_numbers(facts, {"summary": "ρ = 0,27 и 0,29"}) == ""
    assert "0,99" in qwen_reports.check_numbers(facts, {"summary": "ρ = 0,99"})


def test_report_cycle_to_knowledge_base(make_client, exp, settings: Settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    rep = _written(res, settings)
    assert rep["facts"]["experiment"]["code"] == "EXP-001" and rep["facts"]["kpis"][0]["value"] == "+0,27"
    job = db_session.query(QwenJob).filter_by(kind="report").one()
    r = res.post(f"/api/qwen/worker/{job.id}/result", headers=TOKEN, json={"status": "done", "result": {"sections": SECTIONS}})
    assert r.status_code == 200, r.text
    got = res.get("/api/experiments/EXP-001/reports").json()[0]
    assert got["sections"]["verdict"] == "rejected" and got["problems"] == "" and not got["writing"]
    assert res.get(f"/api/reports/{got['id']}/export.docx").status_code == 200
    assert res.post(f"/api/reports/{got['id']}/approve").status_code == 403  # researcher не рецензент
    assert res.post(f"/api/reports/{got['id']}/submit").json()["status"] == "review"
    rev = make_client("rev", "reviewer")
    if not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").exists():
        pytest.skip("нет шрифта DejaVu для PDF (он ставится в образ backend)")
    ok = rev.post(f"/api/reports/{got['id']}/approve")
    assert ok.status_code == 200, ok.text
    imp = db_session.query(KbImport).one()
    assert imp.kb_path == "esg.experiments" and imp.source == "report" and imp.status == "queued"
    assert (Path(settings.kb_inbox_dir) / imp.storage_path).read_bytes().startswith(b"%PDF")


def test_reject_needs_note_and_review_state(make_client, exp, settings: Settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    _written(res, settings)
    job = db_session.query(QwenJob).filter_by(kind="report").one()
    res.post(f"/api/qwen/worker/{job.id}/result", headers=TOKEN, json={"status": "done", "result": {"sections": SECTIONS}})
    rid = res.get("/api/experiments/EXP-001/reports").json()[0]["id"]
    rev = make_client("rev", "reviewer")
    assert rev.post(f"/api/reports/{rid}/reject", json={"note": "нет"}).status_code == 409  # ещё черновик
    res.post(f"/api/reports/{rid}/submit")
    assert rev.post(f"/api/reports/{rid}/reject", json={"note": ""}).status_code == 422
    assert rev.post(f"/api/reports/{rid}/reject", json={"note": "натяжка про Christensen"}).json()["status"] == "rejected"
    assert res.patch(f"/api/reports/{rid}", json={"sections": {"summary": "x"}}).status_code == 409
