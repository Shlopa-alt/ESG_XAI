"""Перевод черновиков данных на русский (п. 6 фидбека): язык, очередь для переводчика на процессоре,
итог — словарь, таблица не меняется. Таблицы — заглушки; слова — общие слова языков, не данные статей."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import DataDraft, QwenJob
from app.services import data_drafts, translation

TOKEN = {"X-Qwen-Token": "tok"}
ONLY_TRANSLATE = {"kinds": ["translate"]}


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok",
                    redis_url="redis://127.0.0.1:1/0")


@pytest.mark.parametrize(("texts", "lang"), [
    (["Total assets of the firms", "Share of women on the board", "[a]"], "en"),
    (["Chiffre d'affaires des entreprises", "Taux de croissance", "année"], "fr"),
    (["Umsatz der Unternehmen", "Anteil", "Jahr", "Größe"], "de"),
    (["إجمالي الأصول", "حصة المرأة"], "ar"),
    (["总资产", "女性董事比例"], "zh"),
    (["Выручка компаний", "Доля женщин"], "ru"),
    (["12", "3,5", "—"], ""),
    # языки, которых переводчик не знает, узнаются — и не уходят в чужую модель
    # (испанский ≠ французский)
    (["Tabla 3 Número de empresas por año", "Tasa de crecimiento de la empresa"], "es"),
    (["Tabela 2 Número de empresas por ano", "Taxa de crescimento não"], "pt"),
    (["Tabella 1 Numero di imprese per anno", "Tasso di crescita delle imprese"], "it"),
    (["Bảng 3. Kiểm định mối quan hệ trực tiếp", "Kết quả"], "vi"),
    (["Şirketlerin toplam varlıkları", "Büyüme oranı"], "tr"),
    (["Виручка підприємств", "Частка жінок у раді"], "uk"),
    (["جدول ۲ میانگین بازده", "شرکت های پذیرفته شده"], "fa"),
    # арабское письмо из PDF — «формы представления» (U+FExx): тоже арабский
    (["ﺍﻟﺎﺩﺎﺮﺓ", "ﺣﺼﺔ"], "ar"),
    (["Òàáëèöà 2 Ýêîëîãè÷åñêèé ïðîôèëü"], ""),  # русский в чужой кодировке — не язык
])
def test_language_is_detected(texts: list[str], lang: str) -> None:
    assert translation.detect(texts) == lang


def test_which_strings_are_translated() -> None:
    f = translation._foreign
    assert f("Total assets") and f("[x] 表 1 样本公司") and f("Umsatz der Unternehmen [тыс. руб.]")
    assert not f("Выручка, тыс. руб.") and not f("12,5") and not f("Выручка [revenue]")
    # коды не переводятся: переводчик делал из них кириллицу («H2» → «Н2», «HQXH» → «ГОК»)
    assert not any(f(x) for x in ("H2", "H1a", "HRM -> HQXH", "PROC-INDEP", "p", "CA"))
    assert f("TOTAL ASSETS") and f("TABLE 2 MEAN VALUES") and f("ESG-gap Pre-Directive")


def test_unsupported_language_is_named_but_not_translated(db_session: Session) -> None:
    """Испанская таблица: язык назван, сама в перевод не встаёт, но перевести вручную можно."""
    job = _job(db_session)
    did = data_drafts.create_from_result(db_session, job, {"drafts": [
        {"doc_id": "[doc-es]", "table_number": 1,
         "columns": ["Empresa", "Tasa de crecimiento del año"],
         "rows": [[f"[empresa {i}]", i] for i in range(5)],
         "caption": "Tabla 1 Número de empresas por año", "title": "[название]"}]})[0]
    db_session.commit()
    d = db_session.get(DataDraft, did)
    assert d is not None
    st = translation.state(db_session, d)
    got = (st["lang"], st["lang_title"], st["supported"], st["can_translate"], st["has_texts"])
    assert got == ("es", "испанский", False, False, True)
    assert not translation._jobs(db_session, d)  # сама не встала
    assert translation.request(db_session, d, "fr") is not None  # вручную — с выбранным языком


def _job(db: Session, kind: str = "tables") -> QwenJob:
    job = QwenJob(kind=kind, status="running", payload={})
    db.add(job)
    db.flush()
    return job


def _drafts(db: Session) -> tuple[int, int]:
    """Таблица английской статьи и таблица русской — из итога задачи «таблицы»."""
    job = _job(db)
    rows_en = [[f"[firm {i}]", "Large" if i % 2 else "Small", i] for i in range(5)]
    rows_ru = [[f"[компания {i}]", "крупная", i] for i in range(5)]
    ids = data_drafts.create_from_result(db, job, {"drafts": [
        {"doc_id": "[doc-en]", "table_number": 1, "columns": ["Firm", "Size of the firm", "Total assets"],
         "rows": rows_en, "caption": "Descriptive statistics of the sample", "title": "[название]"},
        {"doc_id": "[doc-ru]", "table_number": 1, "columns": ["Компания", "Размер", "Активы"],
         "rows": rows_ru, "caption": "Описательная статистика", "title": "[название]"},
    ]})
    db.commit()
    return ids[0], ids[1]


def test_foreign_draft_goes_to_translation_by_itself(db_session: Session) -> None:
    en, ru = _drafts(db_session)
    jobs = db_session.scalars(select(QwenJob).where(QwenJob.kind == "translate")).all()
    assert [j.payload["draft"] for j in jobs] == [en]
    p = jobs[0].payload
    assert p["source"] == "en" and p["target"] == "ru"
    # переводятся заголовки, подпись и текст ячеек; числа и русское — нет
    assert {"Firm", "Size of the firm", "Large", "Small", "Descriptive statistics of the sample"} <= set(p["texts"])
    assert "[название]" not in p["texts"] and not any(isinstance(t, int | float) for t in p["texts"])
    d = db_session.get(DataDraft, ru)
    assert d is not None and translation.request(db_session, d) is None


def test_qwen_worker_never_sees_translation(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    """Перевод — без модели: обработчик Qwen (и прежней версии — без тела запроса) его не берёт и не
    поднимает ради него видеокарту; переводчик берёт только перевод."""
    en, _ = _drafts(db_session)
    db_session.query(QwenJob).filter(QwenJob.kind == "tables").delete()
    db_session.commit()
    c = make_client("own", "owner")
    assert c.post("/api/qwen/worker/peek", headers=TOKEN).json() == {"queued": 0}
    assert c.post("/api/qwen/worker/next", headers=TOKEN).status_code == 204
    assert c.post("/api/qwen/worker/peek", headers=TOKEN, json=ONLY_TRANSLATE).json() == {"queued": 1}
    job = c.post("/api/qwen/worker/next", headers=TOKEN, json=ONLY_TRANSLATE).json()
    assert job["kind"] == "translate" and job["payload"]["draft"] == en
    # перезапуск обработчика Qwen не возвращает в очередь перевод, который сейчас идёт
    assert c.post("/api/qwen/worker/requeue", headers=TOKEN).json() == {"requeued": 0}

    pairs = {"Firm": "Компания", "Size of the firm": "Размер компании", "Large": "Крупная",
             "[не просили]": "[лишнее]", "Small": "  "}
    r = c.post(f"/api/qwen/worker/{job['id']}/result", headers=TOKEN,
               json={"status": "done", "result": {"pairs": pairs, "engine": "argostranslate 1.9"}})
    assert r.status_code == 200, r.text
    assert r.json()["message"].startswith("Переведено строк: 3 из")

    rd = make_client("rd", "reader")
    out = rd.get(f"/api/data-drafts/{en}").json()
    t = out["translation"]
    assert t["lang"] == "en" and t["lang_title"] == "английский" and t["engine"] == "argostranslate 1.9"
    assert t["pairs"] == {"Firm": "Компания", "Size of the firm": "Размер компании", "Large": "Крупная"}
    assert t["pending"] == "" and t["translator_online"] is None
    assert out["columns"][0] == "Firm"  # таблица не меняется — перевод только для чтения
    items = {i["id"]: i for i in rd.get("/api/data-drafts").json()}
    assert items[en]["lang"] == "en"


def test_translate_button(  # type: ignore[no-untyped-def]
    make_client, db_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.data_drafts as api

    monkeypatch.setattr(api, "translator_online", lambda settings: False)  # Redis в тестах нет
    en, ru = _drafts(db_session)
    rd, res = make_client("rd", "reader"), make_client("res", "researcher")
    assert rd.post(f"/api/data-drafts/{en}/translate", json={}).status_code == 403
    assert res.post(f"/api/data-drafts/{ru}/translate", json={}).status_code == 422
    # язык определился неверно — человек указывает свой
    r = res.post(f"/api/data-drafts/{en}/translate", json={"lang": "de"})
    assert r.status_code == 202, r.text
    assert r.json()["translation"]["pending"] == "queued" and r.json()["translation"]["translator_online"] is False
    langs = [j.payload["source"] for j in db_session.scalars(select(QwenJob).where(QwenJob.kind == "translate"))]
    assert langs == ["en", "de"]
    assert res.post(f"/api/data-drafts/{en}/translate", json={"lang": "xx"}).status_code == 422
