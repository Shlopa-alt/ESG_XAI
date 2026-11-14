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


# Похожие идеи — подсказка автору до отправки (п. 5 правок по совещанию).
# SAME — заглушка-перефраз H, OTHER — заглушка на другую тему; не данные статей.
SAME = {"title": "Раскрытие ESG-отчётности и стоимость долга",
        "statement": "Чем полнее раскрытие, тем дешевле заёмный капитал."}
OTHER = {"title": "[другая тема]", "statement": "[утверждение о другом]"}


def test_similar_finds_paraphrase_and_changes_nothing(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("reader1", "reader")
    c.post("/api/hypotheses", json=H)
    r = c.post("/api/hypotheses/similar", json=SAME)
    assert r.status_code == 200, r.text
    [hit] = r.json()
    assert hit["code"] == "H-001" and hit["status"] == "proposed" and hit["share"] >= 0.4
    assert c.post("/api/hypotheses/similar", json=OTHER).json() == []
    assert len(c.get("/api/hypotheses").json()) == 1  # проверка ничего не создаёт


def test_similar_needs_login(client) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/api/hypotheses/similar", json=SAME).status_code == 401


# Тип связи у идеи (п. 6 правок по совещанию): как влияет и на какие показатели.
def test_link_type_and_task_title(make_client, db_session) -> None:  # type: ignore[no-untyped-def]
    from app.models import MethodologySection

    db_session.add(MethodologySection(number="Н1", title="[направление]", content="",
                                      kind="direction", position=1))
    db_session.commit()
    c = make_client("reader1", "reader")
    r = c.post("/api/hypotheses", json={**H, "methodology_node": "Н1", "effect": "increases",
                                        "target_kind": "nonfinancial"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["effect"], body["target_kind"]) == ("increases", "nonfinancial")
    assert (body["methodology_node"], body["methodology_node_title"]) == ("Н1", "[направление]")
    # без типа связи — пусто, как у старых идей и идей ИИ-помощника
    plain = c.post("/api/hypotheses", json=H).json()
    assert (plain["effect"], plain["target_kind"], plain["methodology_node_title"]) == ("", "", "")
    assert c.post("/api/hypotheses", json={**H, "effect": "boosts"}).status_code == 422


def test_weight_set_by_author_changed_by_reviewer(make_client) -> None:  # type: ignore[no-untyped-def]
    author = make_client("reader1", "reader")
    r = author.post("/api/hypotheses", json={**H, "weight": 2})
    assert r.status_code == 201, r.text
    assert (r.json()["weight"], r.json()["weight_set_by"]) == (2, "reader1")
    plain = author.post("/api/hypotheses", json=H).json()
    assert (plain["weight"], plain["weight_set_by"]) == (None, "")
    assert author.post("/api/hypotheses", json={**H, "weight": 4}).status_code == 422
    # автор после отправки вес не меняет — это делает рецензент
    assert author.put("/api/hypotheses/H-001/weight", json={"weight": 3}).status_code == 403
    assert make_client("res", "researcher").put("/api/hypotheses/H-001/weight",
                                                json={"weight": 3}).status_code == 403
    rev = make_client("rev", "reviewer")
    r = rev.put("/api/hypotheses/H-001/weight", json={"weight": 3})
    assert r.status_code == 200 and (r.json()["weight"], r.json()["weight_set_by"]) == (3, "rev")
    assert rev.put("/api/hypotheses/H-001/weight", json={"weight": 0}).status_code == 422
    cleared = rev.put("/api/hypotheses/H-001/weight", json={"weight": None}).json()
    assert (cleared["weight"], cleared["weight_set_by"]) == (None, "rev")
