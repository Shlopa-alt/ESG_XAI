H = {"title": "ESG-раскрытие снижает стоимость капитала",
     "statement": "У компаний с полным ESG-раскрытием стоимость долга ниже при прочих равных.",
     "rationale": "Несколько статей пилота об этом пишут"}


def test_reader_can_propose(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("reader1", "reader")
    r = c.post("/api/hypotheses", json={**H, "refs": [{"kind": "article", "kbrag_id": "doc-1",
                                                        "doi": "10.1/x", "title": "статья"}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "H-001" and body["status"] == "proposed" and body["author"] == "reader1"
    assert body["refs"][0]["doi"] == "10.1/x"
    assert c.post("/api/hypotheses", json=H).json()["code"] == "H-002"


def test_anonymous_cannot_propose(client) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/api/hypotheses", json=H).status_code == 401


def test_only_reviewer_decides_and_reject_needs_reason(make_client) -> None:  # type: ignore[no-untyped-def]
    author = make_client("reader1", "reader")
    author.post("/api/hypotheses", json=H)
    assert author.patch("/api/hypotheses/H-001", json={"status": "accepted"}).status_code == 403
    rev = make_client("rev", "reviewer")
    assert rev.patch("/api/hypotheses/H-001", json={"status": "rejected"}).status_code == 422
    r = rev.patch("/api/hypotheses/H-001", json={"status": "accepted", "note": "проверяемо"})
    assert r.status_code == 200 and r.json()["decided_by"] == "rev"
    assert rev.patch("/api/hypotheses/H-001", json={"status": "rejected", "note": "x"}).status_code == 409


def test_experiment_from_accepted_hypothesis(make_client) -> None:  # type: ignore[no-untyped-def]
    author = make_client("reader1", "reader")
    author.post("/api/hypotheses", json={**H, "refs": [{"kbrag_id": "doc-1", "doi": "10.1/x"}]})
    res = make_client("res", "researcher")
    assert res.post("/api/hypotheses/H-001/experiment").status_code == 409  # ещё не принята
    make_client("rev", "reviewer").patch("/api/hypotheses/H-001", json={"status": "accepted"})
    assert author.post("/api/hypotheses/H-001/experiment").status_code == 403  # reader не может
    r = res.post("/api/hypotheses/H-001/experiment")
    assert r.status_code == 200, r.text
    code = r.json()["experiment"]
    assert r.json()["status"] == "testing" and code.startswith("EXP-")
    exp = res.get(f"/api/experiments/{code}").json()
    assert exp["status"] == "planned" and exp["hypothesis"] == H["statement"]
    assert exp["links"][0]["relation"] == "motivated_by"
