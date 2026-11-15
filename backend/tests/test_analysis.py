"""Анализ данных: рекомендация метода по показателю и данным, запуск в один шаг, NDA.
Столбцы — заглушки, числа — порядковые, не данные компаний (правило 7)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.api.runs as runs_api
from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment, MethodologySection, Run

ROWS = 40
HEADER = ["[компания]", "[отрасль]", "[ROA_2021]", "[ROA_2022]", "[x1]", "[x2]"]


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

    def enqueue(broker: str, run_id: int, job: dict[str, Any], queue: str) -> str:
        sent.append({"job": job, "queue": queue})
        return f"run-{run_id}"

    monkeypatch.setattr(runs_api.run_queue, "enqueue", enqueue)
    return sent


def _snapshot(db: Session, tmp_path: Path, code: str = "DS-09", access: str = "public",
              rows: int = ROWS) -> int:
    path = tmp_path / code / "v1" / "t.csv"
    path.parent.mkdir(parents=True)
    lines = [",".join(HEADER)] + [
        f"[c{i}],[отрасль {i % 3}],{i},{i + 1},{i * 2},{i % 7}" for i in range(rows)
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    ds = Dataset(code=code, title="[набор]", access_level=access)
    db.add(ds)
    db.flush()
    snap = DatasetSnapshot(
        dataset_id=ds.id,
        version="v1",
        sha256="a" * 64,
        storage_path=f"C:/data/{code}/v1/t.csv",
        row_count=rows,
    )
    db.add(snap)
    db.commit()
    return snap.id


def test_target_gives_lab_network_with_reasons(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    sid = _snapshot(db_session, tmp_path)
    r = make_client("rd", "reader").post(
        "/api/analysis/recommend", json={"snapshot_id": sid, "target": "[ROA_2022]"}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["task"]["key"] == "predict" and out["categories"] == ["[отрасль]"]
    first = out["recommendations"][0]
    assert first["template"] == "lab-mlp" and first["primary"] and first["runnable"]
    # прошлый год показателя — не вход, а прогноз «как в прошлом году»; название компании — не категория
    assert first["params"]["lag"] == "[ROA_2021]"
    assert first["params"]["features"] == ["[x1]", "[x2]"] and first["params"]["context"] == [
        "[отрасль]"
    ]
    assert first["why"] and any("меньше 100" in w for w in first["warnings"])
    # альтернативы: та же сеть с заменой на трансформер и быстрая проверка без нейросети
    assert [r["net"] for r in out["recommendations"]] == ["mlp", "transformer", "gbm"]
    assert out["recommendations"][2]["template"] == "predictive-check"


def test_without_target_compares_columns(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sid = _snapshot(db_session, tmp_path)
    out = (
        make_client("rd", "reader")
        .post("/api/analysis/recommend", json={"snapshot_id": sid})
        .json()
    )
    assert out["task"]["key"] == "agreement"
    assert out["recommendations"][0]["template"] == "rank-agreement"
    assert out["recommendations"][0]["params"]["columns"] == [
        "[ROA_2021]",
        "[ROA_2022]",
        "[x1]",
        "[x2]",
    ]
    # вторая карточка — поиск связей по всем столбцам; не основная, и на малых данных не запускается
    scan = out["recommendations"][1]
    assert (scan["template"], scan["primary"]) == ("correlation-scan", False)
    assert scan["params"]["columns"] == ["[ROA_2021]", "[ROA_2022]", "[x1]", "[x2]"]
    assert scan["runnable"]  # 40 строк — ровно минимум
    assert scan["params"]["group"] == ""  # года нет — не панель, строки не усредняются


def test_scan_not_runnable_on_small_data(  # type: ignore[no-untyped-def]
    make_client, db_session: Session, tmp_path: Path,
) -> None:
    sid = _snapshot(db_session, tmp_path, rows=30)
    c = make_client("rd", "reader")
    out = c.post("/api/analysis/recommend", json={"snapshot_id": sid}).json()
    scan = next(r for r in out["recommendations"] if r["template"] == "correlation-scan")
    assert not scan["runnable"] and scan["warnings"]


def test_methodology_item_ranks_target_candidates(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    sid = _snapshot(db_session, tmp_path)
    db_session.add(
        MethodologySection(
            number="1.1.1", title="[задание]: рентабельность активов (ROA)", content="", kind="task"
        )
    )
    db_session.commit()
    out = (
        make_client("rd", "reader")
        .post("/api/analysis/recommend", json={"snapshot_id": sid, "node": "1.1.1"})
        .json()
    )
    cands = [c["column"] for c in out["target_candidates"]]
    assert cands[:2] == [
        "[ROA_2022]",
        "[ROA_2021]",
    ]  # поздний год — результат, ранний — прошлый период
    assert "рентабельность активов" in out["target_candidates"][0]["reason"]


def test_text_target_is_refused(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sid = _snapshot(db_session, tmp_path)
    r = make_client("rd", "reader").post(
        "/api/analysis/recommend", json={"snapshot_id": sid, "target": "[отрасль]"}
    )
    assert r.status_code == 422


def test_nda_columns_only_with_access(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sid = _snapshot(db_session, tmp_path, "DS-10", access="nda")
    body = {"snapshot_id": sid, "target": "[ROA_2022]"}
    assert (
        make_client("res", "researcher").post("/api/analysis/recommend", json=body).status_code
        == 403
    )
    assert make_client("own", "owner").post("/api/analysis/recommend", json=body).status_code == 200


def test_launch_creates_check_and_run_in_one_step(
    make_client,
    db_session: Session,
    tmp_path: Path,  # type: ignore[no-untyped-def]
    queue: list,
) -> None:  # type: ignore[type-arg]
    sid = _snapshot(db_session, tmp_path)
    db_session.add(MethodologySection(number="1.1.1", title="[задание]", content="", kind="task"))
    db_session.commit()
    body = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "node": "1.1.1",
        "params": {
            "target": "[ROA_2022]",
            "features": ["[x1]", "[x2]"],
            "context": ["[отрасль]"],
            "lag": "[ROA_2021]",
            "trials": 3,
        },
        "choice": {"key": "lab-mlp", "title": "[нейросеть]", "why": ["[причина]"], "primary": True},
    }
    assert make_client("rd", "reader").post("/api/analysis/launch", json=body).status_code == 403
    r = make_client("res", "researcher").post("/api/analysis/launch", json=body)
    assert r.status_code == 201, r.text
    exp = db_session.scalar(select(Experiment).where(Experiment.code == r.json()["experiment"]))
    assert exp is not None and exp.status == "running" and exp.dataset_snapshot_id == sid
    assert exp.config["analysis"]["why"] == ["[причина]"] and exp.config["analysis"]["primary"]
    assert "[ROA_2022]" in exp.hypothesis and exp.setup == ["[причина]"]
    run = db_session.get(Run, r.json()["run_id"])
    assert run is not None and run.experiment_id == exp.id and run.config["params"]["trials"] == 3
    assert queue[0]["job"]["experiment"] == exp.code


def test_launch_with_bad_params_leaves_no_check(
    make_client,
    db_session: Session,
    tmp_path: Path,  # type: ignore[no-untyped-def]
    queue: list,
) -> None:  # type: ignore[type-arg]
    sid = _snapshot(db_session, tmp_path)
    c = make_client("res", "researcher")
    bad = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "params": {"target": "[ROA_2022]", "features": ["[ROA_2022]"]},
    }
    assert c.post("/api/analysis/launch", json=bad).status_code == 422
    replication = {"snapshot_id": sid, "template": "exp001-dow30", "params": {}}
    assert c.post("/api/analysis/launch", json=replication).status_code == 422
    assert db_session.scalars(select(Experiment)).all() == [] and queue == []


def test_outcome_columns_beat_input_columns_sharing_words() -> None:
    """«ESG-инвестиции → ROA»: результат — ROA, а не столбцы входов с теми же словами."""
    from app.services.analysis import target_candidates
    from app.services.data_files import Table

    node = MethodologySection(
        number="1.1.1",
        title="[задание]: рентабельность активов (ROA) от ESG-инвестиций",
        content="",
        kind="task",
    )
    cols = ["[ESG-инвестиции: экология]", "[ROA 2022]", "[размер]"]
    t = Table(columns=cols, numeric=set(cols))
    assert [c["column"] for c in target_candidates(node, t)] == ["[ROA 2022]"]


def test_future_years_and_ids_are_not_inputs() -> None:
    """Показатель ROA 2021: ROA 2022 — его будущее (утечка ответа), «год» и «ИНН» — не показатели."""
    from app.services.analysis import recommend
    from app.services.data_files import Table

    cols = ["[ROA 2020]", "[ROA 2021]", "[ROA 2022]", "[год]", "[ИНН]", "[x1]"]
    t = Table(columns=cols, numeric=set(cols), sample=[])
    first = recommend(t, 120, "[ROA 2021]", None)["recommendations"][0]
    assert first["params"]["features"] == ["[x1]"] and first["params"]["lag"] == "[ROA 2020]"
    assert any("[ROA 2022]" in w and "подсмотрел" in w for w in first["why"])


def test_panel_scan_groups_by_entity() -> None:
    """Панель «страна × год»: поиск связей усредняет строки по стране — иначе годы одной страны
    считаются независимыми наблюдениями и связи «подтверждаются» на шуме."""
    from app.services.analysis import panel_group, recommend
    from app.services.data_files import Table

    cols = ["[страна]", "[регион]", "[год]", "[x1]", "[x2]"]
    sample = [[f"[страна {i // 5}]", f"[регион {i % 3}]", 2000 + i % 5, i, i % 7] for i in range(60)]
    t = Table(columns=cols, numeric={"[год]", "[x1]", "[x2]"}, sample=sample)
    assert panel_group(t) == "[страна]"  # больше разных значений, чем у региона
    scan = next(r for r in recommend(t, 600, None, None)["recommendations"]
                if r["template"] == "correlation-scan")
    assert scan["params"]["group"] == "[страна]" and scan["params"]["columns"] == ["[x1]", "[x2]"]
    assert any("усредняются по «[страна]»" in w for w in scan["why"])
    # без столбца года — не панель: группы нет
    flat = Table(columns=["[компания]", "[x1]", "[x2]"], numeric={"[x1]", "[x2]"},
                 sample=[[f"[c{i}]", i, i % 7] for i in range(60)])
    assert panel_group(flat) == ""


def _scan_run(db: Session, sid: int, links: list[tuple[str, str]], status: str = "done") -> int:
    """Готовый расчёт «Поиск связей» с подтверждёнными связями (заглушки столбцов)."""
    exp = Experiment(code="EXP-090", title="[поиск связей]", dataset_snapshot_id=sid)
    db.add(exp)
    db.flush()
    run = Run(experiment_id=exp.id, status=status, template="correlation-scan", dataset_snapshot_id=sid,
              config={"params": {"sheet": "", "group": ""}},
              summary={"links": [{"a": a, "b": b, "kind": "монотонная", "rho": 0.6} for a, b in links],
                       "unit": "row", "confirmed": len(links), "pairs": 6})
    db.add(run)
    db.commit()
    return run.id


def test_link_check_runs_net_set_in_one_check(  # type: ignore[no-untyped-def]
    make_client, db_session: Session, tmp_path: Path, queue: list,
) -> None:
    """«Нейросети»: связь из поиска → одна проверка и расчёт на каждую сеть набора; сводка по сетям."""
    sid = _snapshot(db_session, tmp_path)
    scan = _scan_run(db_session, sid, [("[x1]", "[ROA_2022]")])
    body = {"scan_run": scan, "a": "[x1]", "b": "[ROA_2022]", "target": "[ROA_2022]"}
    assert make_client("rd", "reader").post("/api/analysis/link-check", json=body).status_code == 403
    c = make_client("own", "owner")
    r = c.post("/api/analysis/link-check", json=body)
    assert r.status_code == 201, r.text
    exp = db_session.scalar(select(Experiment).where(Experiment.code == r.json()["experiment"]))
    assert exp is not None and exp.config["link_check"] == {
        "scan_run": scan, "a": "[x1]", "b": "[ROA_2022]", "target": "[ROA_2022]"}
    runs = [db_session.get(Run, i) for i in r.json()["run_ids"]]
    assert [(x.template, x.config["params"].get("architecture")) for x in runs if x] == [
        ("lab-mlp", "mlp"), ("lab-mlp", "transformer"), ("predictive-check", None)]
    assert len(queue) == 3 and all(q["job"]["experiment"] == exp.code for q in queue)
    assert "[x1]" in exp.hypothesis and "не причина" in exp.limitations[0]
    # та же связь ещё раз — не вторая проверка; связи, не подтверждённой поиском, проверять нечего
    assert c.post("/api/analysis/link-check", json=body).status_code == 409
    other = {**body, "a": "[x2]"}
    assert c.post("/api/analysis/link-check", json=other).status_code == 422
    assert c.post("/api/analysis/link-check", json={**body, "target": "[x2]"}).status_code == 422

    out = make_client("rd", "reader").get(f"/api/analysis/links?snapshot_id={sid}").json()
    assert out["scan"]["run_id"] == scan and out["scan"]["links"][0]["a"] == "[x1]"
    check = out["checks"][0]
    assert check["experiment"] == exp.code and [n["net"] for n in check["nets"]] == [
        "mlp", "transformer", "gbm", "linear"]
    assert check["finished"] == 0 and all(n["holds"] is None for n in check["nets"])  # ещё в очереди

    # итоги: держится, если R² выше перемешанной цели и выше 0,05
    mlp, tr, pc = runs
    assert mlp and tr and pc
    mlp.status, mlp.summary = "done", {"mlp_r2_mean": 0.4, "placebo_r2_max": 0.1}
    tr.status, tr.summary = "done", {"mlp_r2_mean": 0.02, "placebo_r2_max": 0.01}
    pc.status, pc.summary = "done", {"r2_mean": {"LightGBM": 0.3, "Линейная (Ridge)": 0.3},
                                     "placebo_max": {"LightGBM": 0.35, "Линейная (Ridge)": 0.05}}
    db_session.commit()
    check = make_client("rd", "reader").get(f"/api/analysis/links?snapshot_id={sid}").json()["checks"][0]
    assert [n["holds"] for n in check["nets"]] == [True, False, False, True]
    assert (check["held"], check["finished"], check["total"]) == (2, 4, 4)


def test_link_check_needs_finished_scan_and_nda_access(  # type: ignore[no-untyped-def]
    make_client, db_session: Session, tmp_path: Path, queue: list,
) -> None:
    sid = _snapshot(db_session, tmp_path)
    scan = _scan_run(db_session, sid, [("[x1]", "[x2]")], status="running")
    body = {"scan_run": scan, "a": "[x1]", "b": "[x2]", "target": "[x2]"}
    assert make_client("own", "owner").post("/api/analysis/link-check", json=body).status_code == 409
    assert db_session.scalars(select(Run).where(Run.template != "correlation-scan")).all() == []
    nda = _snapshot(db_session, tmp_path, code="DS-08", access="nda")
    assert make_client("rd", "reader").get(f"/api/analysis/links?snapshot_id={nda}").status_code == 403
    assert make_client("own", "owner").get(f"/api/analysis/links?snapshot_id={nda}").json()["scan"] is None


def test_prediction_on_panel_splits_by_entity() -> None:
    """Прогноз на панели: группа — страна, и она не попадает в параметры Z."""
    from app.services.analysis import recommend
    from app.services.data_files import Table

    cols = ["[страна]", "[год]", "[x1]", "[x2]"]
    sample = [[f"[страна {i // 5}]", 2000 + i % 5, i, i % 7] for i in range(60)]
    t = Table(columns=cols, numeric={"[год]", "[x1]", "[x2]"}, sample=sample)
    recs = recommend(t, 600, "[x2]", None)["recommendations"]
    for r in recs:
        assert r["params"]["group"] == "[страна]", r["key"]
        assert "[страна]" not in r["params"].get("context", [])
    assert any("которых не было в обучении" in w for w in recs[0]["why"])


def test_net_over_limit_is_skipped_not_the_whole_set(  # type: ignore[no-untyped-def]
    make_client, db_session: Session, tmp_path: Path, queue: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сеть, которая не укладывается в лимит метода (трансформер на больших данных), пропускается
    с причиной; остальные сети набора считаются, итог — из запущенных."""
    import app.api.analysis as api

    real = api._fit_net

    def fit(db, settings, table, rows, rec):  # type: ignore[no-untyped-def]
        if rec["key"] == "lab-mlp:transformer":
            return None, "[больше лимита метода]"
        return real(db, settings, table, rows, rec)

    monkeypatch.setattr(api, "_fit_net", fit)
    sid = _snapshot(db_session, tmp_path)
    scan = _scan_run(db_session, sid, [("[x1]", "[ROA_2022]")])
    body = {"scan_run": scan, "a": "[x1]", "b": "[ROA_2022]", "target": "[ROA_2022]"}
    r = make_client("own", "owner").post("/api/analysis/link-check", json=body)
    assert r.status_code == 201, r.text
    assert len(r.json()["run_ids"]) == 2 and len(queue) == 2
    exp = db_session.scalar(select(Experiment).where(Experiment.code == r.json()["experiment"]))
    assert exp is not None and any("не запускалась: [больше лимита метода]" in x for x in exp.limitations)
    check = make_client("rd", "reader").get(f"/api/analysis/links?snapshot_id={sid}").json()["checks"][0]
    tr = next(n for n in check["nets"] if n["net"] == "transformer")
    assert tr["status"] == "skipped" and tr["reason"] == "[больше лимита метода]" and tr["run_id"] is None
    assert [n["net"] for n in check["nets"]] == ["mlp", "transformer", "gbm", "linear"] and check["total"] == 3


def test_year_is_not_compared_as_an_indicator() -> None:
    from app.services.analysis import recommend
    from app.services.data_files import Table

    cols = ["[страна]", "[год]", "[x1]", "[x2]"]
    t = Table(columns=cols, numeric={"[год]", "[x1]", "[x2]"}, sample=[])
    first = recommend(t, 600, "", None)["recommendations"][0]
    assert first["template"] == "rank-agreement" and first["params"]["columns"] == ["[x1]", "[x2]"]
