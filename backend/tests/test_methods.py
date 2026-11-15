"""Библиотека методов из статей банка: код модели пишет Qwen, платформа проверяет его, администратор
включает, расчёт получает код и его sha256 (правило 3). Статьи, столбцы и числа — заглушки."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.api.runs as runs_api
from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment, Method, QwenJob, Run
from app.services.method_library import check_code

TOKEN = {"X-Qwen-Token": "tok"}
GOOD = '''import numpy as np
from sklearn.neighbors import KNeighborsRegressor

TITLE = "[метод из статьи]"


class Model:
    def __init__(self, params, seed):
        self.m = KNeighborsRegressor(n_neighbors=int(params.get("k", 5)))

    def fit(self, x, y):
        self.m.fit(x, y)
        return self

    def predict(self, x):
        return np.asarray(self.m.predict(x))


def make_model(params, seed):
    return Model(params, seed)


if __name__ == "__main__":
    import protocol
    raise SystemExit(protocol.run(make_model, TITLE))
'''


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok",
                    esg_data_dir=str(tmp_path), esg_data_host="C:/data")


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_api.run_queue, "enqueue",
                        lambda broker, run_id, job, queue: sent.append(job) or f"run-{run_id}")
    return sent


def _job(db: Session) -> int:
    job = QwenJob(kind="method", status="running", trigger="manual", payload={"doc_id": "[статья]"})
    db.add(job)
    db.commit()
    return job.id


def _post(client: Any, job: int, script: str = GOOD, smoke_ok: bool = True) -> Any:
    return client.post("/api/qwen/worker/method", headers=TOKEN, json={
        "job": job, "doc_id": "[статья]", "article_title": "[название статьи]", "doi": "10.0000/[x]",
        "title": "[KNN авторов]", "description": "[описание]", "net": "lstm", "evidence": "[цитата]",
        "params": [{"name": "k", "label": "[соседей]", "default": 5, "min": 1, "max": 50},
                   {"name": "target", "default": 1}, {"name": "bad name", "default": 1}],
        "script": script, "smoke_ok": smoke_ok, "smoke_log": "[журнал пробы]", "fit_s": 0.5, "fit_rows": 200})


def _snapshot(db: Session, tmp_path: Path, rows: int = 60) -> int:
    path = tmp_path / "DS-09" / "v1" / "t.csv"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(["[a],[b],[y]"] + [f"{i},{i % 7},{2 * i}" for i in range(rows)]), encoding="utf-8")
    ds = Dataset(code="DS-09", title="[набор]", access_level="public")
    db.add(ds)
    db.flush()
    snap = DatasetSnapshot(dataset_id=ds.id, version="v1", sha256="a" * 64,
                           storage_path="C:/data/DS-09/v1/t.csv", row_count=rows)
    db.add(snap)
    db.commit()
    return snap.id


def test_code_check_allows_models_and_blocks_files_network_and_tricks() -> None:
    assert check_code(GOOD) == []
    for bad, why in [
        ("import os\n", "«os» не разрешена"),
        ("import socket\n", "«socket» не разрешена"),
        ("from sklearn.datasets import fetch_openml\n", "sklearn.datasets"),
        ("X = open('[файл]')\n", "«open» нельзя"),
        ("X = np.load('[файл]')\n", "«.load»"),
        ("X = make_model.__globals__\n", "__globals__"),
        ("X = eval('1')\n", "«eval» нельзя"),
        ("for i in range(3):\n    pass\n", "на верхнем уровне"),
    ]:
        problems = check_code(GOOD.replace("TITLE = ", bad + "TITLE = ", 1))
        assert any(why in p for p in problems), (bad, problems)
    assert any("make_model" in p for p in check_code(GOOD.replace("def make_model", "def other")))


def test_worker_result_ready_only_if_platform_check_passes(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("own", "owner")
    assert c.post("/api/qwen/worker/method-check", headers=TOKEN, json={"script": "import os"}).json()["problems"]
    assert c.post("/api/qwen/worker/method-check", json={"script": GOOD}).status_code in (401, 403)
    ok = _post(c, _job(db_session)).json()
    # отметке обработчика «проба прошла» платформа не верит: код с файлами — «не прошёл»
    bad = _post(c, _job(db_session), script=GOOD.replace("TITLE = ", "X = open('[файл]')\nTITLE = ")).json()
    assert ok == {"code": "M-01", "status": "ready"} and bad == {"code": "M-02", "status": "failed"}
    m = db_session.scalar(select(Method).where(Method.code == "M-01"))
    assert m is not None and m.sha256 == hashlib.sha256(GOOD.encode()).hexdigest()
    # из гиперпараметров — только целые с правильными именами; цель, входы и группа — протокола
    assert [p["name"] for p in m.params] == ["k"] and m.net == "lstm" and m.doc_id == "[статья]"
    failed = db_session.scalar(select(Method).where(Method.code == "M-02"))
    assert failed is not None and "open" in failed.check_log


def test_owner_enables_after_reading_code_then_method_runs_with_its_code(  # type: ignore[no-untyped-def]
    make_client, db_session: Session, tmp_path: Path, queue: list,
) -> None:
    own, res = make_client("own", "owner"), make_client("res", "researcher")
    _post(own, _job(db_session))
    sid = _snapshot(db_session, tmp_path)
    # до включения метода нет ни в списке расчётов, ни для запуска
    assert not any(t["key"] == "method:M-01" for t in res.get("/api/run-templates").json())
    assert res.post("/api/methods/M-01/enable").status_code == 403
    assert res.get("/api/methods/M-01").json()["script"] == GOOD  # код виден всем — его читают
    assert own.post("/api/methods/M-01/enable").json()["status"] == "enabled"
    assert own.post("/api/methods/M-01/enable").status_code == 409  # уже включён

    tpl = next(t for t in res.get("/api/run-templates").json() if t["key"] == "method:M-01")
    assert [p["name"] for p in tpl["params"]] == ["sheet", "target", "features", "group", "seed", "splits", "k"]
    db_session.add(Experiment(code="EXP-050", title="[проверка]"))
    db_session.commit()
    r = res.post("/api/runs", json={"template": "method:M-01", "snapshot_id": sid, "experiment": "EXP-050",
                                    "params": {"target": "[y]", "features": ["[a]", "[b]"], "k": 7}})
    assert r.status_code == 201, r.text
    job = queue[-1]
    assert job["method_code"] == GOOD and job["method_sha256"] == hashlib.sha256(GOOD.encode()).hexdigest()
    run = db_session.get(Run, r.json()["id"])
    assert run is not None and run.config["method"]["code"] == "M-01" and run.config["params"]["k"] == 7

    # рекомендация прогноза предлагает и метод из статьи
    out = res.post("/api/analysis/recommend", json={"snapshot_id": sid, "target": "[y]"}).json()
    assert any(x["template"] == "method:M-01" and x["net"] == "lstm" for x in out["recommendations"])
    nets = {n["key"]: n for n in res.get("/api/analysis/catalog").json()["nets"]}
    assert nets["lstm"]["runnable"] and nets["lstm"]["template"] == "method:M-01"


def test_from_article_and_reject(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    own, res, rd = make_client("own", "owner"), make_client("res", "researcher"), make_client("rd", "reader")
    assert rd.post("/api/methods/from-article", json={"doc_id": "[статья 2]"}).status_code == 403
    r = res.post("/api/methods/from-article", json={"doc_id": "[статья 2]"})
    assert r.status_code == 202 and db_session.get(QwenJob, r.json()["job"]).kind == "method"  # type: ignore[union-attr]
    assert res.post("/api/methods/from-article", json={"doc_id": "[статья 2]"}).status_code == 409
    assert rd.get("/api/methods").json()["pending"][0]["doc_id"] == "[статья 2]"
    _post(own, _job(db_session))
    assert own.post("/api/methods/M-01/reject", json={"note": ""}).status_code == 422
    out = own.post("/api/methods/M-01/reject", json={"note": "[почему нет]"}).json()
    assert out["status"] == "rejected" and out["decision_note"] == "[почему нет]"
    assert own.post("/api/methods/M-01/enable").status_code == 409
    lib = rd.get("/api/methods").json()
    assert lib["builtin"] and lib["methods"][0]["code"] == "M-01"
