from pathlib import Path

import pytest

import app.api.kb_imports as kb_imports
from app.config import Settings
from app.services.article_fetch import FetchError, _check_public, doc_id_for_doi, normalize_doi

PDF = b"%PDF-1.7\n%test\n"
TOKEN = {"X-Import-Token": "tok"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev",
                    kb_inbox_dir=str(tmp_path), kb_import_token="tok", kb_import_max_mb=1)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тесты не ходят в OpenAlex и KBRAG."""
    def no_openalex(doi: str, timeout_s: float = 30.0) -> dict:  # type: ignore[type-arg]
        raise FetchError("нет сети")

    monkeypatch.setattr(kb_imports, "openalex_work", no_openalex)
    monkeypatch.setattr(kb_imports, "_in_kb", lambda settings, doi: False)


def _upload(c, data: bytes = PDF, **fields: str):  # type: ignore[no-untyped-def]
    return c.post("/api/kb-imports", files={"file": ("Статья 2024.pdf", data, "application/pdf")},
                  data={"kb_path": "esg.ratings", **fields})


def test_reader_cannot_upload(make_client) -> None:  # type: ignore[no-untyped-def]
    assert _upload(make_client("r", "reader")).status_code == 403


def test_upload_rejects_bad_input(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    assert _upload(c, b"<html>").status_code == 422
    assert _upload(c, kb_path="physics").status_code == 422
    assert _upload(c, doi="abc").status_code == 422
    assert _upload(c, b"%PDF-" + b"0" * 2**20).status_code == 413


def test_upload_queues_file_with_metadata(make_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    r = _upload(c, doi="https://doi.org/10.3390/ABC.1", title="Название", year="2024",
                authors="Иванов И.; Petrov P.")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued" and body["doi"] == "10.3390/abc.1"
    assert body["authors"] == ["Иванов И.", "Petrov P."] and body["author"] == "res"
    pdfs = list(Path(settings.kb_inbox_dir).rglob("*.pdf"))
    assert [p.name for p in pdfs] == ["Статья_2024.pdf"] and pdfs[0].read_bytes() == PDF
    meta = pdfs[0].with_suffix(".yaml").read_text(encoding="utf-8")
    assert "10.3390/abc.1" in meta and "Petrov P." in meta
    # тот же файл второй раз — отказ
    assert _upload(c).status_code == 409
    assert [i["id"] for i in c.get("/api/kb-imports").json()] == [body["id"]]


def test_worker_needs_token(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    assert c.post("/api/kb-imports/worker/next").status_code == 403
    assert c.post("/api/kb-imports/worker/next", headers={"X-Import-Token": "x"}).status_code == 403


def test_worker_cycle(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    imp = _upload(c).json()
    job = c.post("/api/kb-imports/worker/next", headers=TOKEN)
    assert job.status_code == 200 and job.json()["id"] == imp["id"]
    assert job.json()["path"].endswith(".pdf")
    assert c.post("/api/kb-imports/worker/next", headers=TOKEN).status_code == 204
    # обработчик перезапустился, не доделав, — статья снова в очереди
    assert c.post("/api/kb-imports/worker/requeue", headers=TOKEN).json() == {"requeued": 1}
    job = c.post("/api/kb-imports/worker/next", headers=TOKEN).json()
    r = c.post(f"/api/kb-imports/worker/{job['id']}/result", headers=TOKEN,
               json={"status": "failed", "message": "скан"})
    assert r.json()["status"] == "failed"
    assert c.post(f"/api/kb-imports/{job['id']}/retry").json()["status"] == "queued"
    job = c.post("/api/kb-imports/worker/next", headers=TOKEN).json()
    r = c.post(f"/api/kb-imports/worker/{job['id']}/result", headers=TOKEN,
               json={"status": "done", "doc_id": "10.3390_abc.1"})
    assert r.json()["status"] == "done" and r.json()["doc_id"] == "10.3390_abc.1"
    assert c.post(f"/api/kb-imports/{job['id']}/retry").status_code == 409


def test_by_doi(make_client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(kb_imports, "openalex_work", lambda doi: {
        "title": "Open article", "year": 2023, "authors": ["A. Author"], "journal": "J",
        "is_oa": True, "pdf_urls": ["https://example.org/a.pdf"]})
    monkeypatch.setattr(kb_imports, "download_pdf", lambda urls, limit: (PDF, urls[0]))
    c = make_client("res", "researcher")
    r = c.post("/api/kb-imports/doi", json={"doi": "doi:10.1371/journal.pone.1", "kb_path": "esg"})
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Open article" and r.json()["source"] == "doi"
    again = c.post("/api/kb-imports/doi", json={"doi": "10.1371/journal.pone.1", "kb_path": "esg"})
    assert again.status_code == 409


def test_doi_helpers() -> None:
    assert normalize_doi(" https://doi.org/10.3390/Electronics14030417. ") == "10.3390/electronics14030417"
    assert doc_id_for_doi("10.1002/bse.3543") == "10.1002_bse.3543"
    with pytest.raises(FetchError):
        normalize_doi("electronics14030417")


@pytest.mark.parametrize("url", ["http://127.0.0.1/a.pdf", "http://10.0.0.5/a.pdf", "file:///etc/passwd"])
def test_no_downloads_from_internal_network(url: str) -> None:
    with pytest.raises(FetchError):
        _check_public(url)
