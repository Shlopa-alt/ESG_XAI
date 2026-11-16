"""Ручной режим (п. 9–10 фидбека): архив с ноутбуком Jupyter, данными и кодом метода; файл версии данных.
Данные — заглушки (порядковые числа), не данные компаний."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment, Run

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev",
                    esg_data_dir=str(tmp_path), esg_data_host="C:/data", repo_dir=str(REPO))


def _setup(db: Session, tmp_path: Path, access: str = "public", code: str = "DS-09") -> tuple[int, int]:
    path = tmp_path / code / "v1" / "t.csv"
    path.parent.mkdir(parents=True)
    path.write_text("[a],[b]\n" + "\n".join(f"{i},{i * 2}" for i in range(50)), encoding="utf-8")
    ds = Dataset(code=code, title="[набор]", access_level=access)
    db.add(ds)
    db.flush()
    snap = DatasetSnapshot(dataset_id=ds.id, version="v1", sha256="a" * 64,
                           storage_path=f"C:/data/{code}/v1/t.csv", row_count=50)
    exp = Experiment(code=f"EXP-0{len(code)}{code[-1]}", title="[проверка]", status="review", config={})
    db.add_all([snap, exp])
    db.flush()
    run = Run(experiment_id=exp.id, status="done", template="correlation-scan", dataset_snapshot_id=snap.id,
              config={"params": {"columns": ["[a]", "[b]"], "group": "", "method": "rank", "holdout": 50,
                                 "fdr": 10, "placebo": 5, "seed": 42, "sheet": "", "flag": True, "none": None}},
              summary={"confirmed": 1, "pairs": 1}, runner_commit="c" * 40, seeds={"split": 42})
    db.add(run)
    db.commit()
    return run.id, snap.id


def _zip(r) -> zipfile.ZipFile:  # type: ignore[no-untyped-def]
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_run_bundle_has_notebook_data_and_method(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    run_id, _ = _setup(db_session, tmp_path)
    r = make_client("rd", "reader").get(f"/api/runs/{run_id}/manual.zip")
    z = _zip(r)
    assert "esg-run-" in r.headers["content-disposition"]
    names = set(z.namelist())
    assert {f"run-{run_id}.ipynb", "README.txt", "platform_run.json", "data/DS-09/v1/t.csv",
            "runner/methods/correlation_scan.py", "runner/methods/common.py",
            "runner/hsu2025/requirements.lock"} <= names
    assert not any("test_" in n or "__pycache__" in n for n in names)  # тесты метода — не в архив
    recorded = json.loads(z.read("platform_run.json"))
    assert recorded["params"]["seed"] == 42 and recorded["runner_commit"] == "c" * 40
    assert recorded["summary"] == {"confirmed": 1, "pairs": 1} and recorded["sha256"] == "a" * 64
    nb = json.loads(z.read(f"run-{run_id}.ipynb"))
    assert nb["nbformat"] == 4
    code = [c["source"] for c in nb["cells"] if c["cell_type"] == "code"]
    for src in code:  # каждая ячейка — правильный Python (параметры — не JSON: True, None)
        compile(src, "<cell>", "exec")
    joined = "\n".join(code)
    assert "'flag': True" in joined and "'none': None" in joined
    assert "correlation_scan.py" in joined and "'--experiment'" in joined and "SHA256 = 'aaaa" in joined
    assert "в реестр платформы сам не попадёт" in z.read("README.txt").decode()


def test_nda_data_only_for_access(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    run_id, snap_id = _setup(db_session, tmp_path, access="nda", code="DS-07")
    rd = make_client("rd", "reader")
    z = _zip(rd.get(f"/api/runs/{run_id}/manual.zip"))
    assert not any(n.startswith("data/") for n in z.namelist())
    assert "NDA" in z.read("README.txt").decode()
    assert rd.get(f"/api/snapshots/{snap_id}/file").status_code == 403
    own = make_client("own", "owner")
    assert "data/DS-07/v1/t.csv" in _zip(own.get(f"/api/runs/{run_id}/manual.zip")).namelist()
    f = own.get(f"/api/snapshots/{snap_id}/file")
    assert f.status_code == 200 and f.headers["x-sha256"] == "a" * 64 and f.content.startswith(b"[a],[b]")


def test_snapshot_bundle_and_login(client, make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _, snap_id = _setup(db_session, tmp_path)
    assert client.get(f"/api/snapshots/{snap_id}/manual.zip").status_code == 401
    assert client.get(f"/api/snapshots/{snap_id}/file").status_code == 401
    z = _zip(make_client("rd", "reader").get(f"/api/snapshots/{snap_id}/manual.zip"))
    assert {"DS-09-v1.ipynb", "dataset.json", "README.txt", "data/DS-09/v1/t.csv"} <= set(z.namelist())
    assert json.loads(z.read("dataset.json"))["version"] == "v1"
    assert "runner/" not in z.read("README.txt").decode()
    assert make_client("rd2", "reader").get("/api/snapshots/999/manual.zip").status_code == 404
