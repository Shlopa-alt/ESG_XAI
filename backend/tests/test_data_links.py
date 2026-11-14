"""Агент сбора данных по ссылкам из статей (задача Qwen data_links): поиск ссылок кодом, приём
файла платформой, черновик со ссылкой на статью и источник, журнал обработки, правило 8.
Статьи, ссылки и таблицы — заглушки; сеть не используется."""

import base64
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import DataDraft, Dataset, DatasetSnapshot

QWEN = Path(__file__).resolve().parents[2] / "runner" / "qwen"
sys.path.insert(0, str(QWEN))
_spec = importlib.util.spec_from_file_location("qwen_data_links", QWEN / "data_links.py")
L = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(L)  # type: ignore[union-attr]

TOKEN = {"X-Qwen-Token": "tok"}
CSV = "[объект],[a],[b]\n[x],1,\"1 234,5\"\n[y],2,3\n[z],4,5\n".encode()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok",
                    esg_data_dir=str(tmp_path), esg_data_host="C:/data", link_max_mb=1)


def _file(data: bytes = CSV, name: str = "[data].csv", sha: str | None = None) -> dict[str, Any]:
    return {"url": "https://zenodo.org/records/1/files/data.csv", "name": name, "size": len(data),
            "sha256": sha or hashlib.sha256(data).hexdigest(), "content_b64": base64.b64encode(data).decode()}


def _item(**kw: Any) -> dict[str, Any]:
    return {"doc_id": "[статья]", "kb_path": "esg", "article_title": "[название статьи]", "doi": "10.0000/[x]",
            "source_url": "https://zenodo.org/records/1", "link_context": "[The data are available at zenodo]",
            "reason": "репозиторий данных (zenodo.org)", "title": "[набор авторов]", "description": "[что в нём]",
            "why": "[почему данные авторов]", "file": _file(), "failure": "", **kw}


def _job(c: Any) -> int:
    job = c.post("/api/data-drafts/links-scan", json={"doc_id": "[статья]"}).json()["job"]
    assert c.post("/api/qwen/worker/next", headers=TOKEN).json()["kind"] == "data_links"
    return int(job)


# --- агент: поиск ссылок кодом ---


def test_finds_data_links_and_skips_articles_and_licenses() -> None:
    text = ("[Intro]. See https://doi.org/10.1016/j.x.2020.1 for the method. Licensed under "
            "https://creativecommons.org/licenses/by/4.0/. The data are available at https://zenodo.org/records/42. "
            "Replication files: https://github.com/u/r/blob/main/data/panel.csv. Raw survey: 10.5281/zenodo.77.")
    found = {f["url"]: f for f in L.find_links(text)}
    assert "https://zenodo.org/records/42" in found and "репозиторий" in found["https://zenodo.org/records/42"]["reason"]
    assert "https://github.com/u/r/blob/main/data/panel.csv" in found
    assert "https://doi.org/10.5281/zenodo.77" in found
    assert not any("creativecommons" in u or "10.1016" in u for u in found)
    assert "data are available" in found["https://zenodo.org/records/42"]["context"]


def test_repository_pages_resolve_to_files_without_network() -> None:
    assert L.github_raw("https://github.com/u/r/blob/main/d/x.csv") == "https://raw.githubusercontent.com/u/r/main/d/x.csv"
    assert L.zenodo_id("https://zenodo.org/records/42") == "42" and L.zenodo_id("https://doi.org/10.5281/zenodo.77") == "77"
    assert L.figshare_id("https://figshare.com/articles/dataset/name/123456") == "123456"
    assert L.resolve("https://example.org/data/table.xlsx", 10) == [("table.xlsx", "https://example.org/data/table.xlsx")]


def test_downloads_only_from_public_addresses() -> None:
    with pytest.raises(L.FetchError, match="внутреннюю сеть"):
        L.check_public("http://127.0.0.1:8000/data.csv")
    with pytest.raises(L.FetchError, match="http"):
        L.check_public("ftp://example.org/data.csv")


def test_docling_text_includes_hyperlinks() -> None:
    doc = {"texts": [{"text": "[Data availability]", "hyperlink": "https://osf.io/abcd"}]}
    assert "https://osf.io/abcd" in L.article_text(doc)


# --- платформа: черновик, файл, происхождение ---


def test_link_draft_has_article_source_file_and_processing(make_client, db_session: Session,  # type: ignore[no-untyped-def]
                                                          tmp_path: Path) -> None:
    c = make_client("res", "researcher")
    job = _job(c)
    url = "/api/qwen/worker/link-drafts"
    assert c.post(url, json={"job": job, "drafts": [_item()]}).status_code == 403  # без токена
    r = c.post(url, headers=TOKEN, json={"job": job, "drafts": [_item()]})
    assert r.status_code == 200 and len(r.json()["created"]) == 1
    # повтор той же ссылки той же статьи — не задваивается; агент узнаёт её из links-context
    assert c.post(url, headers=TOKEN, json={"job": job, "drafts": [_item()]}).json()["created"] == []
    known = c.post("/api/qwen/worker/links-context", headers=TOKEN).json()["known"]
    assert known == [["[статья]", "https://zenodo.org/records/1"]]
    d = c.get(f"/api/data-drafts/{r.json()['created'][0]}").json()
    assert d["source_kind"] == "link" and d["source_url"] == "https://zenodo.org/records/1"
    assert d["file_sha256"] == hashlib.sha256(CSV).hexdigest() and d["file_url"].endswith("data.csv")
    assert d["columns"] == ["[объект]", "[a]", "[b]"] and d["rows"][0] == ["[x]", 1.0, 1234.5]
    kinds = [h["kind"] for h in d["history"]]
    assert kinds == ["found", "download", "parse"] and "data are available" in d["history"][0]["text"]
    stored = db_session.get(DataDraft, d["id"])
    assert stored is not None and Path(stored.file_path).read_bytes() == CSV
    done = c.post(f"/api/qwen/worker/{job}/result", headers=TOKEN, json={"status": "done", "result": {"sent": 1}}).json()
    assert "по ссылкам из статей: 1" in done["message"]


def test_dataset_keeps_original_file_and_terms_of_the_article(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    job = _job(c)
    did = c.post("/api/qwen/worker/link-drafts", headers=TOKEN, json={"job": job, "drafts": [_item()]}).json()["created"][0]
    r = c.post(f"/api/data-drafts/{did}/approve", json={"title": "[набор из статьи]"})
    assert r.status_code == 200, r.text
    ds = db_session.scalar(select(Dataset).where(Dataset.code == r.json()["dataset"]))
    assert ds is not None and ds.source_url == "https://zenodo.org/records/1"
    assert "Условия использования определяет статья" in ds.description
    assert "[название статьи]" in ds.description and "sha256" in ds.description
    snap = db_session.scalar(select(DatasetSnapshot).where(DatasetSnapshot.dataset_id == ds.id))
    assert snap is not None and snap.sha256 == hashlib.sha256(CSV).hexdigest()  # исходный файл как есть


def test_not_downloadable_link_is_a_draft_without_table(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    job = _job(c)
    item = _item(source_url="https://data.mendeley.com/datasets/[x]", file=None,
                 failure="по ссылке нет файла таблицы, который можно скачать автоматически")
    did = c.post("/api/qwen/worker/link-drafts", headers=TOKEN, json={"job": job, "drafts": [item]}).json()["created"][0]
    d = c.get(f"/api/data-drafts/{did}").json()
    assert d["rows"] == [] and "Файл не скачан" in d["history"][1]["text"]
    r = c.post(f"/api/data-drafts/{did}/approve", json={"title": "[набор]"})
    assert r.status_code == 422 and "скачайте данные по ссылке" in r.json()["detail"]


def test_damaged_or_oversized_file_is_refused(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    job = _job(c)
    bad = _item(source_url="https://zenodo.org/records/2", file=_file(sha="0" * 64))
    big = _item(source_url="https://zenodo.org/records/3", file=_file(data=b"x" * (2 * 2**20)))
    ids = c.post("/api/qwen/worker/link-drafts", headers=TOKEN, json={"job": job, "drafts": [bad, big]}).json()["created"]
    texts = [c.get(f"/api/data-drafts/{i}").json()["history"][1]["text"] for i in ids]
    assert "sha256 не совпал" in texts[0] and "больше 1 МБ" in texts[1]


def test_scan_of_all_articles_is_for_owner(make_client) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    assert res.post("/api/data-drafts/links-scan", json={}).status_code == 403
    assert res.post("/api/data-drafts/links-scan", json={"doc_id": "[статья]"}).status_code == 202
    assert make_client("own", "owner").post("/api/data-drafts/links-scan", json={}).status_code == 202
    assert make_client("rd", "reader").post("/api/data-drafts/links-scan", json={"doc_id": "[x]"}).status_code == 403
