"""Командная строка esg (cli/esg_cli.py) против платформы: запросы CLI идут в тестовое приложение.
Данные — заглушки (порядковые числа)."""

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment, Run

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("esg_cli", REPO / "cli" / "esg_cli.py")
C = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(C)  # type: ignore[union-attr]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev",
                    esg_data_dir=str(tmp_path / "srv"), esg_data_host="C:/data", repo_dir=str(REPO))


class Through(C.Api):  # type: ignore[misc,name-defined]
    """Api CLI, но запросы — в тестовое приложение (вход уже выполнен клиентом)."""

    def __init__(self, client: TestClient, home: Path) -> None:
        super().__init__(home)
        self.client, self.url = client, "http://test"

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, bytes, dict[str, str]]:
        r = self.client.request(method, path, json=body, headers=self.headers())
        return r.status_code, r.content, {k.lower(): v for k, v in r.headers.items()}


def _data(db: Session, tmp_path: Path) -> tuple[int, int]:
    path = tmp_path / "srv" / "DS-09" / "v1" / "t.csv"
    path.parent.mkdir(parents=True)
    path.write_text("[a],[b]\n" + "\n".join(f"{i},{i * 2}" for i in range(50)), encoding="utf-8")
    ds = Dataset(code="DS-09", title="[набор]", access_level="public")
    db.add(ds)
    db.flush()
    snap = DatasetSnapshot(dataset_id=ds.id, version="v1", sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           storage_path="C:/data/DS-09/v1/t.csv", row_count=50)
    exp = Experiment(code="EXP-010", title="[проверка]", status="review", config={})
    db.add_all([snap, exp])
    db.flush()
    run = Run(experiment_id=exp.id, status="done", template="correlation-scan", dataset_snapshot_id=snap.id,
              config={"params": {"columns": ["[a]", "[b]"], "seed": 42}}, summary={"confirmed": 1}, seeds={})
    db.add(run)
    db.commit()
    return run.id, snap.id


def _cli(api: Any, *argv: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = C.main(list(argv), api)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_read_download_and_notebook(make_client, db_session: Session, tmp_path: Path,  # type: ignore[no-untyped-def]
                                    capsys: pytest.CaptureFixture[str]) -> None:
    run_id, snap_id = _data(db_session, tmp_path)
    api = Through(make_client("rd", "reader"), tmp_path / "home")
    code, out, _ = _cli(api, "datasets", capsys=capsys)
    assert code == 0 and "DS-09" in out and "[набор]" in out
    code, out, _ = _cli(api, "dataset", "DS-09", capsys=capsys)
    assert code == 0 and f"{snap_id}" in out and "v1" in out
    code, out, _ = _cli(api, "download", str(snap_id), "-o", str(tmp_path / "dl"), capsys=capsys)
    assert code == 0 and "совпадает" in out and (tmp_path / "dl" / "t.csv").read_text().startswith("[a],[b]")
    code, out, _ = _cli(api, "notebook", "--run", str(run_id), "-o", str(tmp_path / "work"), capsys=capsys)
    assert code == 0, out
    folder = next((tmp_path / "work").iterdir())
    assert (folder / f"run-{run_id}.ipynb").is_file() and (folder / "data" / "DS-09" / "v1" / "t.csv").is_file()
    assert "jupyter notebook" in out
    code, out, _ = _cli(api, "runs", "--experiment", "EXP-010", capsys=capsys)
    assert code == 0 and "correlation-scan" in out
    code, out, _ = _cli(api, "run", str(run_id), capsys=capsys)
    assert code == 0 and '"seed": 42' in out and '"confirmed": 1' in out


def test_errors_are_plain_and_rules_hold(make_client, db_session: Session, tmp_path: Path,  # type: ignore[no-untyped-def]
                                         capsys: pytest.CaptureFixture[str]) -> None:
    _data(db_session, tmp_path)
    reader = Through(make_client("rd", "reader"), tmp_path / "home")
    # читатель не запускает расчёты — ответ платформы, а не трассировка
    code, _, err = _cli(reader, "launch", "correlation-scan", "--snapshot", "1", "--experiment", "EXP-010",
                        "--param", "method=partial", capsys=capsys)
    assert code == 1 and err.startswith("esg: Платформа ответила 403")
    # свой расчёт без коммита репозитория — не в реестр (правило 3), платформу даже не спрашиваем
    run_json = tmp_path / "run.json"
    run_json.write_text(json.dumps({"runner_commit": "", "summary": {}}), encoding="utf-8")
    code, _, err = _cli(reader, "upload-run", "EXP-010", str(run_json), capsys=capsys)
    assert code == 1 and "правило 3" in err
    code, _, err = _cli(reader, "download", "999", capsys=capsys)
    assert code == 1 and "404" in err


def test_params_and_no_address(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert C.parse_params(['columns=["a","b"]', "holdout=50", "method=partial", "flag=true"], None) == {
        "columns": ["a", "b"], "holdout": 50, "method": "partial", "flag": True}
    with pytest.raises(C.CliError):
        C.parse_params(["без-равно"], None)
    code, _, err = _cli(C.Api(tmp_path / "empty"), "datasets", capsys=capsys)
    assert code == 1 and "esg login --url" in err


def test_token_login_without_password(make_client, db_session: Session, tmp_path: Path,  # type: ignore[no-untyped-def]
                                      settings: Settings, capsys: pytest.CaptureFixture[str],
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Скрипт без пароля: токен API в ESG_TOKEN; «только чтение» не запускает расчёты."""
    from app.main import app

    site = make_client("tok", "researcher")
    token = site.post("/api/tokens", json={"name": "скрипт", "scope": "read"}).json()["token"]
    monkeypatch.setenv("ESG_TOKEN", token)
    api = Through(TestClient(app), tmp_path / "home")  # без cookie сессии — только токен
    code, out, _ = _cli(api, "whoami", capsys=capsys)
    assert code == 0 and "tok (researcher)" in out and "токен API" in out
    code, _, err = _cli(api, "launch", "correlation-scan", "--snapshot", "1", "--experiment", "EXP-001",
                        capsys=capsys)
    assert code == 1 and "только для чтения" in err
    monkeypatch.setenv("ESG_TOKEN", "esg_forged")
    code, _, err = _cli(Through(TestClient(app), tmp_path / "home"), "datasets", capsys=capsys)
    assert code == 1 and "Токен API не принят" in err
