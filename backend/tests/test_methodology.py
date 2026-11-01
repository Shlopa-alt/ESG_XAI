import pytest
from sqlalchemy.orm import Session

from app.models import Experiment, MethodologySection, MethodologyVersion


@pytest.fixture
def seeded(db_session: Session) -> None:
    db_session.add(MethodologySection(number="5", title="Проверка моделей", content="старый текст",
                                      stability="draft"))
    db_session.add(MethodologyVersion(version="0.1", sections_content={
        "5": {"title": "Проверка моделей", "content": "старый текст", "stability": "draft"}}))
    db_session.add(Experiment(code="EXP-900", title="завершён", status="done", config={},
                              setup=[], results=[], limitations=[], reproducibility=[]))
    db_session.add(Experiment(code="EXP-901", title="на проверке", status="review", config={},
                              setup=[], results=[], limitations=[], reproducibility=[]))
    db_session.commit()


def _cr(c, code: str = "CR-90"):  # type: ignore[no-untyped-def]
    r = c.post("/api/change-requests", json={"code": code, "section": "5", "title": "новые проверки",
                                             "proposed_content": "новый текст"})
    assert r.status_code == 201, r.text
    return r.json()


def test_accept_without_basis_and_review_is_refused(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    _cr(owner)
    r = owner.patch("/api/change-requests/CR-90", json={"status": "accepted"})
    assert r.status_code == 422
    assert "основания" in r.json()["detail"] and "рецензии" in r.json()["detail"]


def test_unfinished_experiment_is_not_a_basis(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    _cr(owner)
    owner.post("/api/change-requests/CR-90/bases", json={"basis_type": "experiment",
                                                         "experiment_code": "EXP-901"})
    owner.post("/api/change-requests/CR-90/reviews", json={"verdict": "approve"})
    assert owner.patch("/api/change-requests/CR-90", json={"status": "accepted"}).status_code == 422


def test_kb_article_without_doi_is_not_a_basis(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    _cr(owner)
    owner.post("/api/change-requests/CR-90/bases", json={"basis_type": "kb_article",
                                                         "kbrag_id": "doc-1", "doi": ""})
    owner.post("/api/change-requests/CR-90/reviews", json={"verdict": "approve"})
    assert owner.patch("/api/change-requests/CR-90", json={"status": "accepted"}).status_code == 422


def test_accept_with_done_experiment_and_approval(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    _cr(owner)
    owner.post("/api/change-requests/CR-90/bases", json={"basis_type": "experiment",
                                                         "experiment_code": "EXP-900"})
    rev = make_client("rev", "reviewer")
    assert rev.post("/api/change-requests/CR-90/reviews", json={"verdict": "approve"}).status_code == 201
    r = owner.patch("/api/change-requests/CR-90", json={"status": "accepted"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted" and r.json()["target_version"] == "0.2"
    m = owner.get("/api/methodology").json()
    assert m["version"] == "0.2"
    assert m["sections"][0]["content"] == "новый текст"
    assert m["sections"][0]["stability"] == "stable"
    d = owner.get("/api/methodology/diff", params={"from": "0.1", "to": "0.2"}).json()
    assert d[0]["number"] == "5"


def test_fact_with_quote_is_a_basis(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    _cr(owner)
    owner.post("/api/change-requests/CR-90/bases", json={
        "basis_type": "kb_fact", "kbrag_id": "fact-17", "quote": "ESG disclosure reduces cost of capital"})
    owner.post("/api/change-requests/CR-90/reviews", json={"verdict": "approve"})
    assert owner.patch("/api/change-requests/CR-90", json={"status": "accepted"}).status_code == 200


def test_only_owner_accepts(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    _cr(res)
    assert res.patch("/api/change-requests/CR-90", json={"status": "accepted"}).status_code == 403


def test_researcher_cannot_review_cr(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    _cr(res)
    assert res.post("/api/change-requests/CR-90/reviews", json={"verdict": "approve"}).status_code == 403
