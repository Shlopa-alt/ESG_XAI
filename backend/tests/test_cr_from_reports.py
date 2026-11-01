"""Шаг 6: по одобренному отчёту Qwen предлагает CR; принимается он по обычному правилу 2."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ChangeRequest, CrBasis, Experiment, ExperimentReport, MethodologySection, QwenJob

TOKEN = {"X-Qwen-Token": "tok"}
DRAFT = {"decision": "change", "reason": "", "section": "Н1.В1.З1", "action": "add", "new_kind": "section",
         "new_title": "Несколько провайдеров", "title": "Сверять рейтинги нескольких провайдеров",
         "description": "ρ = 0,27 незначим", "proposed_content": "Не опираться на один рейтинг."}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok",
                    kb_inbox_dir=str(tmp_path))


@pytest.fixture
def report(db_session: Session) -> int:
    n1 = MethodologySection(number="Н1", title="Направление", content="н1", kind="direction", position=1)
    other = MethodologySection(number="Н2", title="Другое", content="н2", kind="direction", position=2)
    o1 = MethodologySection(number="О1", title="Общий раздел", content="прежнее правило", kind="section", position=1)
    db_session.add_all([n1, other, o1])
    db_session.flush()
    z1 = MethodologySection(number="Н1.В1.З1", title="Задание", content="з1", kind="task", parent_id=n1.id, position=1)
    db_session.add(z1)
    db_session.flush()
    exp = Experiment(code="EXP-001", title="[...]", status="done", config={}, setup=[], results=[], limitations=[],
                     reproducibility=[], methodology_node_id=z1.id)
    db_session.add(exp)
    db_session.flush()
    r = ExperimentReport(experiment_id=exp.id, version=1, status="approved",
                         facts={"experiment": {"code": "EXP-001"}, "kpis": [{"value": "+0,27"}]},
                         sections={"summary": "[...]", "verdict": "rejected", "methodology": "[...]"})
    db_session.add(r)
    db_session.commit()
    return r.id


def _qwen_answers(c, answer: dict) -> dict:  # type: ignore[no-untyped-def,type-arg]
    job = c.post("/api/qwen/worker/next", headers=TOKEN).json()
    assert job["kind"] == "cr"
    ctx = c.post("/api/qwen/worker/cr-context", headers=TOKEN, json={"report": job["payload"]["report"]}).json()
    # ветка эксперимента и общие разделы, без чужого направления Н2
    assert [t["number"] for t in ctx["targets"]] == ["Н1", "Н1.В1.З1", "О1"]
    r = c.post(f"/api/qwen/worker/{job['id']}/result", headers=TOKEN, json={"status": "done", "result": answer})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_qwen_proposes_cr_with_experiment_basis(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    assert res.post(f"/api/reports/{report}/cr").json()["cr_writing"] is True
    assert res.post(f"/api/reports/{report}/cr").status_code == 409  # уже готовит
    job = _qwen_answers(res, DRAFT)
    cr = db_session.query(ChangeRequest).one()
    assert job["message"].startswith(f"Предложен {cr.code}")
    assert cr.source == "qwen" and cr.status == "proposed" and cr.action == "add" and cr.author_id is None
    assert db_session.query(CrBasis).filter_by(cr_id=cr.id, basis_type="experiment").count() == 1
    out = res.get("/api/change-requests").json()[0]
    assert out["report"] == "EXP-001 v1" and out["author"] == "Qwen" and out["editable"]
    assert out["blockers"] == ["нет одобряющей рецензии"]  # основание есть, одобрения ещё нет
    assert res.get("/api/experiments/EXP-001/reports").json()[0]["cr"] == cr.code
    assert res.post(f"/api/reports/{report}/cr").status_code == 409  # CR уже есть


def test_draft_outside_experiment_branch_is_dropped(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    res.post(f"/api/reports/{report}/cr")
    job = _qwen_answers(res, {**DRAFT, "section": "Н2"})
    assert "отброшен" in job["message"] and db_session.query(ChangeRequest).count() == 0
    assert "отброшен" in res.get("/api/experiments/EXP-001/reports").json()[0]["cr_note"]


def test_add_respects_child_kinds_and_none_decision(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    res.post(f"/api/reports/{report}/cr")
    assert "нельзя добавить" in _qwen_answers(res, {**DRAFT, "new_kind": "variant"})["message"]
    res.post(f"/api/reports/{report}/cr")
    assert "не нужно" in _qwen_answers(res, {**DRAFT, "decision": "none", "reason": "ничего не меняет"})["message"]
    assert db_session.query(ChangeRequest).count() == 0


def test_numbers_and_unfinished_experiment_are_flagged(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    db_session.query(Experiment).one().status = "review"
    db_session.commit()
    res = make_client("res", "researcher")
    res.post(f"/api/reports/{report}/cr")
    _qwen_answers(res, {**DRAFT, "description": "ρ = 0,99"})
    cr = db_session.query(ChangeRequest).one()
    assert "0,99" in cr.problems and "станет годным" in cr.problems


def test_text_editable_until_approval(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    res.post(f"/api/reports/{report}/cr")
    _qwen_answers(res, DRAFT)
    code = db_session.query(ChangeRequest).one().code
    assert make_client("rd", "reader").patch(f"/api/change-requests/{code}", json={"title": "чужая правка"}).status_code == 403
    r = res.patch(f"/api/change-requests/{code}", json={"title": "Сверять три рейтинга", "description": "ρ = 0,27"})
    assert r.status_code == 200 and r.json()["title"] == "Сверять три рейтинга" and r.json()["status"] == "proposed"
    rev = make_client("rev", "reviewer")
    rev.post(f"/api/change-requests/{code}/reviews", json={"verdict": "approve"})
    assert res.patch(f"/api/change-requests/{code}", json={"title": "после одобрения"}).status_code == 409
    owner = make_client("boss", "owner")
    ok = owner.patch(f"/api/change-requests/{code}", json={"status": "accepted"})
    assert ok.status_code == 200, ok.text
    assert db_session.query(MethodologySection).filter_by(number="Н1.В1.З1.Р1").one().title == "Несколько провайдеров"


def test_approve_with_methodology_enqueues_cr(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    if not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").exists():
        pytest.skip("нет шрифта DejaVu для PDF (он ставится в образ backend)")
    db_session.get(ExperimentReport, report).status = "review"
    db_session.commit()
    assert make_client("rev", "reviewer").post(f"/api/reports/{report}/approve").status_code == 200
    job = db_session.query(QwenJob).filter_by(kind="cr").one()
    assert job.payload == {"report": report} and job.trigger == "report"


def test_latin_lookalikes_in_node_number(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    res.post(f"/api/reports/{report}/cr")
    _qwen_answers(res, {**DRAFT, "section": "H1.B1.31"})  # латиница и цифра 3 вместо «З»
    assert db_session.query(ChangeRequest).one().section_id == db_session.query(MethodologySection).filter_by(
        number="Н1.В1.З1").one().id


def test_qwen_edits_only_sections_and_appends(make_client, report: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    res.post(f"/api/reports/{report}/cr")
    edit = {**DRAFT, "action": "edit", "new_kind": "", "new_title": ""}
    assert "только разделы" in _qwen_answers(res, {**edit, "section": "Н1.В1.З1"})["message"]
    assert db_session.query(ChangeRequest).count() == 0
    res.post(f"/api/reports/{report}/cr")
    _qwen_answers(res, {**edit, "section": "О1"})
    cr = db_session.query(ChangeRequest).one()
    assert cr.action == "edit" and cr.proposed_content == "прежнее правило\n\nНе опираться на один рейтинг."
