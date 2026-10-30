from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Dataset

CSV = b"a,b\n1,2\n3,4\n"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev",
                    esg_data_dir=str(tmp_path), esg_data_host="C:/data", dataset_upload_max_mb=1)


def _new(c, **fields: str):  # type: ignore[no-untyped-def]
    return c.post("/api/datasets", json={"title": "Тестовый набор", **fields})


def test_reader_cannot_create(make_client) -> None:  # type: ignore[no-untyped-def]
    assert _new(make_client("r", "reader")).status_code == 403


def test_create_gets_next_code(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    db_session.add(Dataset(code="DS-05", title="есть", access_level="public"))
    db_session.commit()
    r = _new(make_client("res", "researcher"))
    assert r.status_code == 201 and r.json()["code"] == "DS-06"


def test_only_owner_sets_nda(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    code = _new(c).json()["code"]
    assert c.patch(f"/api/datasets/{code}", json={"access_level": "nda"}).status_code == 403
    assert c.patch(f"/api/datasets/{code}", json={"title": "Новое имя"}).json()["title"] == "Новое имя"


def test_upload_snapshot_counts_rows_and_refuses_duplicate(make_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    code = _new(c).json()["code"]
    r = c.post(f"/api/datasets/{code}/snapshots", files={"file": ("data.csv", CSV)}, data={"version": "v1"})
    assert r.status_code == 201, r.text
    snap = r.json()["snapshots"][0]
    assert snap["version"] == "v1" and snap["row_count"] == 2
    assert snap["storage_path"] == f"C:\data\{code}\snapshots\v1\data.csv"
    assert (Path(settings.esg_data_dir) / code / "snapshots" / "v1" / "data.csv").read_bytes() == CSV
    again = c.post(f"/api/datasets/{code}/snapshots", files={"file": ("other.csv", CSV)})
    assert again.status_code == 409


def test_register_server_file_stays_inside_dataset(make_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    code = _new(c).json()["code"]
    root = Path(settings.esg_data_dir) / code / "raw"
    root.mkdir(parents=True)
    (root / "x.csv").write_bytes(CSV)
    (Path(settings.esg_data_dir) / "secret.csv").write_bytes(b"secret")
    assert [f["path"] for f in c.get(f"/api/datasets/{code}/files").json()] == ["raw/x.csv"]
    assert c.post(f"/api/datasets/{code}/snapshots/register", json={"path": "../secret.csv"}).status_code == 422
    r = c.post(f"/api/datasets/{code}/snapshots/register", json={"path": "raw/x.csv"})
    assert r.status_code == 201 and r.json()["snapshots"][0]["row_count"] == 2
    # та же дата — версия получает суффикс
    (root / "y.csv").write_bytes(CSV + b"5,6\n")
    r = c.post(f"/api/datasets/{code}/snapshots/register", json={"path": "raw/y.csv"})
    versions = [s["version"] for s in r.json()["snapshots"]]
    assert versions[0] == versions[1] + "-2"


def test_nda_files_hidden_from_non_owner(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    db_session.add(Dataset(code="DS-03", title="ОЭЗ", access_level="nda"))
    db_session.commit()
    c = make_client("res", "researcher")
    assert c.get("/api/datasets/DS-03").json()["can_see_files"] is False
    assert c.get("/api/datasets/DS-03/files").status_code == 403
    assert c.post("/api/datasets/DS-03/snapshots", files={"file": ("d.csv", CSV)}).status_code == 403
    owner = make_client("boss", "owner")
    assert owner.get("/api/datasets/DS-03").json()["can_see_files"] is True
