"""Черновики датасетов из таблиц статей: операции правки, поток «обработчик → черновик → датасет»,
команды Qwen. Таблицы и статьи — заглушки."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import DataDraft, Dataset, DatasetSnapshot, QwenJob
from app.services import data_drafts as svc

TOKEN = {"X-Qwen-Token": "tok"}
COLS = ["[объект]", "[а]", "[б]"]
ROWS: list[list[Any]] = [
    ["[x]", 1.0, "[текст]"],
    ["[y]", 2.0, None],
    ["Всего", 3.0, None],
    ["[z]", 4.0, "1 234,5"],
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        auth_backend="local",
        secret_key="test",
        local_dev_password="dev",
        qwen_token="tok",
        esg_data_dir=str(tmp_path),
        esg_data_host="C:/data",
    )


def _draft(**kw: Any) -> dict[str, Any]:
    return {
        "doc_id": "[статья]",
        "kb_path": "esg",
        "article_title": "[название статьи]",
        "doi": "10.0000/[x]",
        "table_number": 3,
        "page": 7,
        "caption": "[подпись]",
        "title": "[таблица наблюдений]",
        "description": "[строка — объект]",
        "columns": COLS,
        "rows": ROWS,
        "notes": ["[разбор: пометка]"],
        **kw,
    }


def _finish(c: Any, job_id: int, result: dict[str, Any]) -> dict[str, Any]:
    assert c.post("/api/qwen/worker/next", headers=TOKEN).json()["id"] == job_id
    r = c.post(
        f"/api/qwen/worker/{job_id}/result",
        headers=TOKEN,
        json={"status": "done", "result": result},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _scan(c: Any, drafts: list[dict[str, Any]]) -> dict[str, Any]:
    job = c.post("/api/data-drafts/scan", json={"doc_id": "[статья]"}).json()["job"]
    return _finish(c, job, {"drafts": drafts})


def test_scan_of_all_articles_is_for_owner(make_client) -> None:  # type: ignore[no-untyped-def]
    """Поиск по всем статьям занимает очередь Qwen надолго, по одной статье — нет."""
    res = make_client("res", "researcher")
    assert res.post("/api/data-drafts/scan", json={}).status_code == 403
    assert res.post("/api/data-drafts/scan", json={"doc_id": "[статья]"}).status_code == 202
    assert make_client("own", "owner").post("/api/data-drafts/scan", json={}).status_code == 202


def test_worker_sends_drafts_in_batches(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    job = c.post("/api/data-drafts/scan", json={"doc_id": "[статья]"}).json()["job"]
    c.post("/api/qwen/worker/next", headers=TOKEN)
    url = "/api/qwen/worker/tables-drafts"
    assert c.post(url, json={"job": job, "drafts": [_draft()]}).status_code == 403  # без токена обработчика
    r = c.post(url, headers=TOKEN, json={"job": job, "drafts": [_draft()]})
    assert r.status_code == 200 and len(r.json()["created"]) == 1
    # повтор той же порции после обрыва связи черновик не задваивает
    assert c.post(url, headers=TOKEN, json={"job": job, "drafts": [_draft()]}).json()["created"] == []
    assert c.post(url, headers=TOKEN, json={"job": 999999, "drafts": []}).status_code == 404
    done = c.post(f"/api/qwen/worker/{job}/result", headers=TOKEN, json={"status": "done", "result": {"drafts": []}}).json()
    assert done["message"] == "Черновиков данных: 1"


# --- операции ---


def test_ops_apply_on_copy_and_describe() -> None:
    cols, rows, done = svc.apply(
        COLS,
        ROWS,
        [
            {"op": "drop_rows_where", "column": "[объект]", "test": "equals", "value": "Всего"},
            {"op": "to_number", "column": "[б]"},
            {"op": "rename", "column": "[а]", "to": "[а, руб.]"},
            {"op": "scale", "column": "[а, руб.]", "factor": 1000},
        ],
    )
    assert cols == ["[объект]", "[а, руб.]", "[б]"]
    assert rows == [["[x]", 1000.0, None], ["[y]", 2000.0, None], ["[z]", 4000.0, 1234.5]]
    assert "не числа стали пропуском: 1" in done[1]
    assert ROWS[2][0] == "Всего"  # исходная таблица не тронута


@pytest.mark.parametrize(
    "op",
    [
        {"op": "rename", "column": "[нет]", "to": "[в]"},
        {"op": "rename", "column": "[а]", "to": "[б]"},
        {"op": "drop_columns", "columns": COLS},
        {"op": "drop_rows", "rows": [9]},
        {"op": "keep_rows_where", "column": "[а]", "test": "[как угодно]"},
        {"op": "scale", "column": "[а]", "factor": 0},
        {"op": "exec", "code": "[код]"},
    ],
)
def test_bad_ops_are_refused(op: dict[str, Any]) -> None:
    with pytest.raises(svc.OpError):
        svc.apply(COLS, ROWS, [op])


def test_transpose_and_keep_where() -> None:
    cols, rows, _ = svc.apply(
        ["[показатель]", "2015", "2016"],
        [["[а]", 1.0, 2.0], ["[б]", 3.0, 4.0]],
        [{"op": "transpose"}],
    )
    assert cols == ["[показатель]", "[а]", "[б]"] and rows == [
        ["2015", 1.0, 3.0],
        ["2016", 2.0, 4.0],
    ]
    _, kept, _ = svc.apply(
        COLS, ROWS, [{"op": "keep_rows_where", "column": "[а]", "test": "greater", "value": "1,5"}]
    )
    assert [r[0] for r in kept] == ["[y]", "Всего", "[z]"]


def test_csv_keeps_all_digits() -> None:
    d = DataDraft(columns=["[а]", "[б]"], rows=[[5838951.7, "[x]"], [12.0, None]])
    assert svc.to_csv(d) == "[а],[б]\n5838951.7,[x]\n12,\n"


# --- поток ---


def test_worker_result_creates_drafts_once(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    job = _scan(
        c, [_draft(), _draft(table_number=4, rows=[["[x]", 1.0, None]])]
    )  # 1 строка — не черновик
    assert len(job["result"]["created"]) == 1
    d = db_session.query(DataDraft).one()
    assert d.history[0]["kind"] == "parse" and d.history[0]["text"] == "[разбор: пометка]"
    ctx = c.post("/api/qwen/worker/tables-context", headers=TOKEN).json()
    assert ctx["known"] == [["[статья]", 3]]
    assert _scan(c, [_draft()])["result"]["created"] == []  # та же таблица статьи — повтор


def test_reader_sees_but_cannot_edit(make_client) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    _scan(res, [_draft()])
    reader = make_client("rd", "reader")
    d = reader.get("/api/data-drafts").json()[0]
    assert reader.get(f"/api/data-drafts/{d['id']}").status_code == 200
    assert reader.patch(f"/api/data-drafts/{d['id']}", json={"title": "[x]"}).status_code == 403
    assert (
        reader.post(f"/api/data-drafts/{d['id']}/command", json={"text": "[команда]"}).status_code
        == 403
    )


def test_manual_edit_goes_to_history(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _scan(c, [_draft()])
    did = c.get("/api/data-drafts").json()[0]["id"]
    r = c.patch(
        f"/api/data-drafts/{did}",
        json={
            "title": "[новое название]",
            "ops": [
                {"op": "drop_rows", "rows": [2]},
                {"op": "set_cell", "row": 1, "column": "[б]", "value": "7,5"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert (
        d["title"] == "[новое название]" and d["n_rows"] == 3 and d["rows"][1] == ["[y]", 2.0, 7.5]
    )
    assert d["history"][-1]["kind"] == "manual" and d["history"][-1]["who"] == "res"
    bad = c.patch(
        f"/api/data-drafts/{did}", json={"ops": [{"op": "rename", "column": "[нет]", "to": "[в]"}]}
    )
    assert bad.status_code == 422 and "Нет столбца" in bad.json()["detail"]


def test_qwen_command_becomes_ops(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _scan(c, [_draft()])
    did = c.get("/api/data-drafts").json()[0]["id"]
    assert (
        c.post(
            f"/api/data-drafts/{did}/command", json={"text": "убери итоговую строку"}
        ).status_code
        == 202
    )
    job = db_session.query(QwenJob).filter_by(kind="table_edit").one()
    assert job.payload == {"draft": did, "command": "убери итоговую строку"}
    ctx = c.post("/api/qwen/worker/draft-context", headers=TOKEN, json={"draft": did}).json()
    assert ctx["columns"] == COLS and ctx["row_count"] == 4
    done = _finish(
        c,
        job.id,
        {
            "ops": [
                {"op": "drop_rows_where", "column": "[объект]", "test": "equals", "value": "Всего"}
            ],
            "explanation": "[пояснение]",
        },
    )
    assert done["message"].startswith("Сделано")
    d = c.get(f"/api/data-drafts/{did}").json()
    assert (
        d["n_rows"] == 3 and d["history"][-1]["kind"] == "qwen" and d["jobs"][0]["status"] == "done"
    )


def test_qwen_bad_ops_leave_table(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _scan(c, [_draft()])
    did = c.get("/api/data-drafts").json()[0]["id"]
    c.post(f"/api/data-drafts/{did}/command", json={"text": "[команда]"})
    job = db_session.query(QwenJob).filter_by(kind="table_edit").one()
    done = _finish(c, job.id, {"ops": [{"op": "exec", "code": "[код]"}]})
    assert done["message"].startswith("Не выполнено")
    assert c.get(f"/api/data-drafts/{did}").json()["n_rows"] == 4


def test_approve_creates_dataset_with_provenance(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    settings: Settings,
) -> None:
    c = make_client("res", "researcher")
    _scan(c, [_draft()])
    did = c.get("/api/data-drafts").json()[0]["id"]
    r = c.post(f"/api/data-drafts/{did}/approve", json={"title": "[датасет из статьи]"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["dataset"].startswith("DS-")
    ds = db_session.query(Dataset).one()
    assert ds.source_url == "https://doi.org/10.0000/[x]"
    assert "Таблица 3 (с. 7)" in ds.description and "[разбор: пометка]" in ds.description
    # правило 8: таблица — производные данные, условия задаёт статья
    assert "Условия использования определяет статья" in ds.description
    assert "требует источника" not in ds.description
    snap = db_session.query(DatasetSnapshot).one()
    files = list(Path(settings.esg_data_dir).rglob("*.csv"))
    assert len(files) == 1 and files[0].read_text(encoding="utf-8").startswith(
        "[объект],[а],[б]\n[x],1,[текст]"
    )
    assert snap.row_count == 4
    assert c.post(f"/api/data-drafts/{did}/reject", json={"note": "[причина]"}).status_code == 409


def test_reject_hides_from_open_list(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _scan(c, [_draft()])
    did = c.get("/api/data-drafts").json()[0]["id"]
    assert (
        c.post(f"/api/data-drafts/{did}/reject", json={"note": "[не наблюдения]"}).json()["status"]
        == "rejected"
    )
    assert c.get("/api/data-drafts").json() == []
    assert len(c.get("/api/data-drafts?status=all").json()) == 1
