"""Подбор сети по статье: классификация «задача → сети», сеть авторов в тексте, «как у авторов»
первой карточкой, выбор и причина — в проверке. Тексты статей и столбцы — заглушки."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.api.runs as runs_api
from app.config import Settings
from app.models import (
    Dataset,
    DatasetSnapshot,
    ExperimentLink,
    ExperimentProposal,
    Hypothesis,
    HypothesisRef,
    KbRef,
)
from app.services import kb_text, net_catalog
from app.services.run_templates import TEMPLATES, ParamError, check_params

HEADER = ["[компания]", "[R]", "[x1]", "[x2]"]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        auth_backend="local",
        secret_key="test",
        local_dev_password="dev",
        esg_data_dir=str(tmp_path),
        esg_data_host="C:/data",
    )


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runs_api.run_queue,
        "enqueue",
        lambda broker, run_id, job, queue: sent.append(job) or f"run-{run_id}",
    )
    return sent


def _snapshot(db: Session, tmp_path: Path) -> int:
    path = tmp_path / "DS-09" / "v1" / "t.csv"
    path.parent.mkdir(parents=True)
    rows = [f"[c{i}],{i},{i * 2},{i % 5}" for i in range(40)]
    path.write_text("\n".join([",".join(HEADER), *rows]), encoding="utf-8")
    ds = Dataset(code="DS-09", title="[набор]", access_level="public")
    db.add(ds)
    db.flush()
    snap = DatasetSnapshot(
        dataset_id=ds.id,
        version="v1",
        sha256="a" * 64,
        storage_path="C:/data/DS-09/v1/t.csv",
        row_count=40,
    )
    db.add(snap)
    db.commit()
    return snap.id


def _idea(db: Session, status: str = "accepted", quote: str = "") -> str:
    h = Hypothesis(
        code="H-001", title="[идея]", statement="[утверждение]", status=status, suggested={}
    )
    ref = KbRef(kind="article", kbrag_id="[doc]", title="[статья-источник]", quote=quote)
    db.add_all([h, ref])
    db.flush()
    db.add(HypothesisRef(hypothesis_id=h.id, kb_ref_id=ref.id))
    db.commit()
    return h.code


def test_catalog_marks_what_is_runnable(make_client) -> None:  # type: ignore[no-untyped-def]
    out = make_client("rd", "reader").get("/api/analysis/catalog").json()
    tasks = {t["key"]: t for t in out["tasks"]}
    assert tasks["predict"]["nets"][:2] == ["mlp", "transformer"]
    nets = {n["key"]: n for n in out["nets"]}
    assert nets["mlp"]["runnable"] and nets["transformer"]["runnable"]
    assert not nets["lstm"]["runnable"] and nets["lstm"]["nearest"] == "transformer"


def test_authors_net_is_the_most_mentioned_network_with_quote() -> None:
    text = (
        "[введение]. We use XGBoost as a baseline. The proposed multilayer perceptron (MLP) "
        "predicts ROA. The MLP has one hidden layer."
    )
    found = net_catalog.authors_net(text)
    assert found is not None and found["net"] == "mlp" and found["runnable"]
    assert "multilayer perceptron" in found["quote"] and "gbm" in found["also"]
    lstm = net_catalog.authors_net("[текст]. Мы обучили LSTM на рядах показателей.")
    assert lstm is not None and not lstm["runnable"] and lstm["nearest"] == "transformer"
    assert net_catalog.authors_net("[текст без названий сетей]") is None


def test_architecture_is_checked_on_server() -> None:
    lab = TEMPLATES["lab-mlp"]
    cols, num = ["[R]", "[x]"], {"[R]", "[x]"}
    assert (
        check_params(lab, {"target": "[R]", "features": ["[x]"]}, cols, num)["architecture"]
        == "mlp"
    )
    ok = check_params(
        lab, {"target": "[R]", "features": ["[x]"], "architecture": "transformer"}, cols, num
    )
    assert ok["architecture"] == "transformer"
    with pytest.raises(ParamError):
        check_params(lab, {"target": "[R]", "features": ["[x]"], "architecture": "cnn"}, cols, num)


def test_idea_with_article_puts_as_authors_first(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _snapshot(db_session, tmp_path)
    code = _idea(db_session)
    monkeypatch.setattr(
        kb_text,
        "article_text",
        lambda settings, doc: "[название]\nWe train a Transformer with self-attention.",
    )
    out = (
        make_client("rd", "reader")
        .post(
            "/api/analysis/recommend",
            json={"snapshot_id": sid, "target": "[R]", "hypothesis": code},
        )
        .json()
    )
    first, *rest = out["recommendations"]
    assert first["key"] == "authors:transformer" and first["as_authors"] and first["primary"]
    assert (
        first["params"]["architecture"] == "transformer" and "self-attention" in first["evidence"]
    )
    assert "[статья-источник]" in first["why"][0]
    mlp = next(r for r in rest if r["net"] == "mlp")
    assert not mlp["primary"] and mlp["why"][0].startswith("Замена сети авторов")
    assert (
        out["hypothesis"]["code"] == code and out["authors"]["article_title"] == "[статья-источник]"
    )


def test_network_missing_from_library_is_shown_honestly(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _snapshot(db_session, tmp_path)
    code = _idea(db_session, quote="[цитата]: a random forest model was estimated")

    def down(settings: Settings, doc: str) -> str:
        raise LookupError("[банк недоступен]")

    monkeypatch.setattr(kb_text, "article_text", down)
    out = (
        make_client("rd", "reader")
        .post(
            "/api/analysis/recommend",
            json={"snapshot_id": sid, "target": "[R]", "hypothesis": code},
        )
        .json()
    )
    first = out["recommendations"][0]
    assert first["key"] == "authors:rf" and not first["runnable"] and first["as_authors"]
    gbm = next(r for r in out["recommendations"] if r["net"] == "gbm")
    assert gbm["why"][0].startswith("Ближайшая замена")


def test_launch_from_idea_records_choice_and_reason(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    queue: list,
) -> None:  # type: ignore[type-arg]
    sid = _snapshot(db_session, tmp_path)
    code = _idea(db_session)
    idea_id = db_session.scalar(select(Hypothesis.id).where(Hypothesis.code == code))
    db_session.add(
        ExperimentProposal(hypothesis_id=idea_id, status="proposed", title="[предложение Qwen]")
    )
    db_session.commit()
    body = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "hypothesis": code,
        "expected": "[подтвердит: R² трансформера выше плацебо]",
        "params": {"target": "[R]", "features": ["[x1]", "[x2]"], "architecture": "transformer"},
        "choice": {
            "key": "authors:transformer",
            "title": "[как у авторов]",
            "why": ["[причина]"],
            "primary": True,
            "net": "transformer",
            "as_authors": True,
            "evidence": "[цитата]",
            "article": "[статья-источник]",
            "task": "predict",
        },
    }
    c = make_client("res", "researcher")
    r = c.post("/api/analysis/launch", json=body)
    assert r.status_code == 201, r.text
    exp = c.get(f"/api/experiments/{r.json()['experiment']}").json()
    choice = exp["config"]["analysis"]
    assert (
        choice["as_authors"] and choice["evidence"] == "[цитата]" and choice["net"] == "transformer"
    )
    assert exp["hypothesis"] == "[утверждение]" and exp["status"] == "running"
    h = db_session.scalar(select(Hypothesis).where(Hypothesis.code == code))
    assert h is not None and h.status == "testing"
    assert db_session.scalars(select(ExperimentLink)).all()  # источник идеи — основание проверки
    assert queue[0]["params"]["architecture"] == "transformer"
    assert any("Что подтвердит или опровергнет" in x for x in exp["setup"])
    # как в мастере: ждущие предложения Qwen закрыты, проверка записана одобренным предложением
    props = db_session.scalars(select(ExperimentProposal)).all()
    assert [(p.status, p.expected) for p in props] == [
        ("rejected", ""),
        ("approved", "[подтвердит: R² трансформера выше плацебо]"),
    ]
    # затем — замена сети: второй расчёт той же идеи идёт в ту же проверку, критерий уже записан
    swap = {
        **body,
        "expected": "",
        "params": {**body["params"], "architecture": "mlp"},
        "choice": {
            "key": "lab-mlp:mlp",
            "title": "[замена]",
            "why": ["[замена сети]"],
            "net": "mlp",
        },
    }
    r2 = c.post("/api/analysis/launch", json=swap)
    assert r2.status_code == 201, r2.text and r2.json()["experiment"] == r.json()["experiment"]
    runs = c.get(f"/api/experiments/{r.json()['experiment']}").json()["config"]["analysis_runs"]
    assert [x["net"] for x in runs] == ["transformer", "mlp"] and runs[1]["run_id"] != runs[0][
        "run_id"
    ]


def test_criterion_is_required_for_an_idea(
    make_client,
    db_session: Session,
    tmp_path: Path,
    queue: list,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    sid = _snapshot(db_session, tmp_path)
    code = _idea(db_session)
    body = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "hypothesis": code,
        "params": {"target": "[R]", "features": ["[x1]"]},
    }
    r = make_client("res", "researcher").post("/api/analysis/launch", json=body)
    assert (
        r.status_code == 422 and "подтвердит или опровергнет" in r.json()["detail"] and queue == []
    )


def test_network_changed_by_hand_is_marked(
    make_client,
    db_session: Session,
    tmp_path: Path,
    queue: list,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    """Карточка «как у авторов: перцептрон», а в параметрах выбран трансформер — в проверке написано,
    что считали трансформер и сеть заменили вручную."""
    sid = _snapshot(db_session, tmp_path)
    body = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "params": {"target": "[R]", "features": ["[x1]"], "architecture": "transformer"},
        "choice": {
            "key": "authors:mlp",
            "title": "[как у авторов: MLP]",
            "why": ["[причина]"],
            "primary": True,
            "net": "mlp",
            "as_authors": True,
        },
    }
    r = make_client("res", "researcher").post("/api/analysis/launch", json=body)
    assert r.status_code == 201, r.text
    exp = make_client("rd", "reader").get(f"/api/experiments/{r.json()['experiment']}").json()
    c = exp["config"]["analysis"]
    assert (
        c["net"] == "transformer" and c["replaced"] == "mlp" and c["edited"] and not c["as_authors"]
    )
    assert c["why"][0].startswith("Сеть заменена вручную")


def test_launch_needs_accepted_idea(
    make_client,
    db_session: Session,
    tmp_path: Path,  # type: ignore[no-untyped-def]
    queue: list,
) -> None:  # type: ignore[type-arg]
    sid = _snapshot(db_session, tmp_path)
    code = _idea(db_session, status="proposed")
    body = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "hypothesis": code,
        "params": {"target": "[R]", "features": ["[x1]"]},
    }
    assert (
        make_client("res", "researcher").post("/api/analysis/launch", json=body).status_code == 409
    )
    assert queue == []


def test_references_and_names_do_not_decide_the_network() -> None:
    """Сеть авторов — по тексту статьи: названия чужих работ в списке литературы и имя «Ann» не в счёт."""
    body = "[введение]. We estimate OLS. Panel OLS is robust. OLS again.\n" + "[текст] " * 40
    refs = (
        "\nReferences\n[1] Smith. MLP networks for ESG. [2] Ann Lee. ANN forecasting. MLP. MLP.\n"
    )
    found = net_catalog.authors_net(body + refs)
    assert found is not None and found["net"] == "linear"
    assert (
        net_catalog.authors_net("[текст] Ann Lee collected the data. We use OLS.")["net"]
        == "linear"
    )  # type: ignore[index]
    assert (
        net_catalog.authors_net("[текст] We train an ANN. The ANN has one layer.")["net"] == "mlp"
    )  # type: ignore[index]
