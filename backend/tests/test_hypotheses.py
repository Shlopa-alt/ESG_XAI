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


def test_similar_tested_idea_shows_what_was_tried(  # type: ignore[no-untyped-def]
    make_client, db_session,
) -> None:
    from app.models import Dataset, DatasetSnapshot, Experiment, Hypothesis, Run

    c = make_client("reader1", "reader")
    c.post("/api/hypotheses", json=H)
    used, other = Dataset(code="DS-01", title="[набор 1]"), Dataset(code="DS-02", title="[набор 2]")
    db_session.add_all([used, other])
    db_session.flush()
    snap = DatasetSnapshot(dataset_id=used.id, version="[версия]", sha256="0" * 64)
    exp = Experiment(code="EXP-001", title="[проверка]", status="done", outcome="rejected")
    db_session.add_all([snap, exp])
    db_session.flush()
    db_session.add(Run(experiment_id=exp.id, template="rank-agreement",
                       dataset_snapshot_id=snap.id))
    h = db_session.query(Hypothesis).filter_by(code="H-001").one()
    h.experiment_id, h.status = exp.id, "tested"
    db_session.commit()

    [hit] = c.post("/api/hypotheses/similar", json=SAME).json()
    t = hit["tried"]
    assert (t["experiment"], t["status"], t["outcome"]) == ("EXP-001", "done", "rejected")
    assert [d["code"] for d in t["datasets"]] == ["DS-01"]
    assert [m["code"] for m in t["methods"]] == ["rank-agreement"]
    # предлагает то, чего ещё не пробовали: другой набор данных и другие методы библиотеки
    assert [d["code"] for d in t["other_datasets"]] == ["DS-02"]
    assert t["other_methods"] and "rank-agreement" not in [m["code"] for m in t["other_methods"]]
    assert all(m["code"] not in ("exp001-dow30", "exp007-hsu") for m in t["other_methods"])


def test_similar_untested_idea_has_no_tried(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("reader1", "reader")
    c.post("/api/hypotheses", json=H)
    assert c.post("/api/hypotheses/similar", json=SAME).json()[0]["tried"] is None


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
