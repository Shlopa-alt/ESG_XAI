"""Анализ данных: рекомендация метода по показателю и набору данных и расчёт в один шаг.

Рекомендацию смотрит любой вошедший (столбцы версии данных под NDA — только с допуском, как и
выгрузка файлов: правило 6). Запуск — researcher+: создаёт проверку EXP-NNN с пунктом методики,
данными, методом и причиной выбора и ставит расчёт метода библиотеки (app/api/runs.py: start_run —
там же проверки параметров, среза и лимитов). Воспроизводимость расчёт фиксирует сам (правило 3).

С идеей для проверки (hypothesis): платформа ищет в статье-источнике, какой сетью пользовались
авторы, и ставит первой карточку «как у авторов» (app/services/net_catalog.py). Проверка по идее
создаётся только из принятой идеи, источники переносятся как основания (SPEC, раздел 3).
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.runs import snapshot_table, start_run
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    ExperimentProposal,
    Hypothesis,
    HypothesisRef,
    KbRef,
    MethodologySection,
    Run,
    User,
)
from app.services import analysis, kb_text, net_catalog, resources
from app.services import method_library as lib
from app.services.codes import next_code
from app.services.data_files import Table
from app.services.qwen_experiments import close_open_proposals, experiment_from_hypothesis
from app.services.run_templates import ParamError, check_params

router = APIRouter(prefix="/analysis", tags=["analysis"])

Researcher = Depends(require_role("researcher"))
MAX_ARTICLES = 3  # статей-источников, в которых ищем сеть авторов


class RecommendIn(BaseModel):
    snapshot_id: int
    sheet: str = ""
    target: str = ""  # целевой показатель; пусто — сравнить показатели между собой
    node: str = ""  # пункт методики (номер), к которому относится анализ
    hypothesis: str = ""  # идея для проверки (H-NNN): «как у авторов» по её статье


class Choice(BaseModel):
    """Что выбрал человек и почему — пишется в проверку (config.analysis) и видно на её странице."""

    key: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=512)
    why: list[str] = Field(default_factory=list, max_length=20)
    primary: bool = False  # выбрана рекомендация платформы, а не альтернатива
    net: str = Field(default="", max_length=64)
    as_authors: bool = False  # повтор с сетью авторов статьи
    evidence: str = Field(default="", max_length=2000)  # цитата статьи о сети авторов
    article: str = Field(default="", max_length=1024)
    task: str = Field(default="", max_length=64)


class LaunchIn(BaseModel):
    snapshot_id: int
    template: str
    params: dict[str, Any] = Field(default_factory=dict)
    node: str = ""
    hypothesis: str = ""
    # по идее: что подтвердит или опровергнет её — записывается до расчёта, как в мастере
    expected: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=512)
    choice: Choice = Field(default_factory=Choice)


class LaunchOut(BaseModel):
    experiment: str
    run_id: int


class LinkCheckIn(BaseModel):
    """Связь из поиска связей — проверить набором сетей: предсказать target по остальным столбцам."""

    scan_run: int  # расчёт «Поиск связей», где связь подтвердилась
    a: str = Field(min_length=1, max_length=512)
    b: str = Field(min_length=1, max_length=512)
    target: str = Field(min_length=1, max_length=512)  # a или b — что предсказываем
    node: str = ""
    # какие сети считать (net_id: mlp, transformer, gbm или ключ метода из статьи); пусто — весь
    # набор. Проверка этой связи уже есть — сети, которых в ней не было, добавляются к ней
    nets: list[str] = Field(default_factory=list, max_length=20)


class LinkCheckOut(BaseModel):
    experiment: str
    run_ids: list[int]
    added: bool = False  # сети добавлены к уже идущей проверке этой связи


def _node(db: Session, number: str) -> MethodologySection | None:
    if not number:
        return None
    node = db.scalar(select(MethodologySection).where(MethodologySection.number == number))
    if node is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Нет пункта методики {number}")
    return node


def _snapshot(db: Session, sid: int) -> tuple[DatasetSnapshot, Dataset]:
    snap = db.get(DatasetSnapshot, sid)
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    if snap is None or ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет версии данных №{sid}")
    return snap, ds


def _hypothesis(db: Session, code: str) -> Hypothesis | None:
    if not code:
        return None
    h = db.scalar(select(Hypothesis).where(Hypothesis.code == code))
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет идеи для проверки {code}")
    return h


def _refs(db: Session, h: Hypothesis) -> list[KbRef]:
    return list(
        db.scalars(
            select(KbRef)
            .join(HypothesisRef, HypothesisRef.kb_ref_id == KbRef.id)
            .where(HypothesisRef.hypothesis_id == h.id)
        )
    )


def authors(settings: Settings, refs: list[KbRef]) -> tuple[dict[str, Any] | None, str]:
    """Сеть авторов по статьям-источникам идеи: текст статьи из банка (не хранится), иначе — то,
    что записано в источнике (название и цитата). Возвращает (сеть с цитатой, пояснение)."""
    articles = [r for r in refs if r.kind == "article"][:MAX_ARTICLES]
    if not articles:
        return None, "У идеи нет статьи-источника — сеть авторов не определить."
    unavailable = []
    for ref in articles:
        try:
            text = kb_text.article_text(settings, ref.kbrag_id)
        except LookupError as exc:
            unavailable.append(str(exc))
            text = f"{ref.title}\n{ref.quote}"
        found = net_catalog.authors_net(text)
        if found is not None:
            return {**found, "article_title": ref.title, "doc_id": ref.kbrag_id}, ""
    if unavailable:
        return None, f"Текст статьи недоступен ({unavailable[0]}); в источнике сеть не названа."
    return None, "В статье-источнике не названа сеть или метод — рекомендация по данным."


@router.get("/catalog", dependencies=[Depends(current_user)])
def catalog(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Классификация «тип задачи → рекомендуемые сети» и что из них считается в платформе —
    вместе с включёнными методами из статей банка."""
    return net_catalog.catalog({m.net: f"{lib.PREFIX}{m.code}" for m in lib.enabled(db) if m.net})


def _library(db: Session) -> list[tuple[Any, str]]:
    """Включённые методы из статей: шаблон расчёта и сеть каталога (lstm, cnn…)."""
    return [(lib.template_of(m), m.net) for m in lib.enabled(db)]


@router.post("/recommend")
def recommend(
    body: RecommendIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    snap, ds = _snapshot(db, body.snapshot_id)
    table = snapshot_table(db, settings, snap, user, body.sheet)  # NDA — только с допуском
    h = _hypothesis(db, body.hypothesis)
    found, note = authors(settings, _refs(db, h)) if h is not None else (None, "")
    if found is not None and not found.get("runnable"):
        # сети авторов нет среди встроенных, но есть метод из статьи с этой сетью — повторить можно
        m = next((m for m in lib.enabled(db) if m.net == found.get("net")), None)
        if m is not None:
            found = {**found, "runnable": True, "template": f"{lib.PREFIX}{m.code}", "params": {}}
    node = _node(db, body.node)
    if node is None and h is not None and h.methodology_node_id:
        node = db.get(MethodologySection, h.methodology_node_id)
    try:
        rows = resources.rows_of(settings, snap, table.sheet)
        out = analysis.recommend(table, rows, body.target, node, found, _library(db))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        "snapshot": {"id": snap.id, "dataset": ds.code, "title": ds.title, "version": snap.version},
        **out,
        "authors_note": out["authors_note"] or note,
        "hypothesis": (
            {
                "code": h.code,
                "title": h.title,
                "statement": h.statement,
                "status": h.status,
                "node": node.number if node else "",
            }
            if h is not None
            else None
        ),
    }


@router.post("/launch", response_model=LaunchOut, status_code=status.HTTP_201_CREATED)
def launch(
    body: LaunchIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
) -> LaunchOut:
    """Проверка EXP-NNN и расчёт — одним действием. Не встал расчёт — нет и проверки."""
    t = lib.template(db, body.template)  # метод из статьи — только включённый
    if t is None or t.scope != "generic":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Анализ данных запускает только общие методы библиотеки",
        )
    snap, ds = _snapshot(db, body.snapshot_id)
    node = _node(db, body.node)
    h = _hypothesis(db, body.hypothesis)
    # идея уже проверяется — следующий расчёт (например, замена сети авторов) идёт в ту же проверку
    existing = (
        db.get(Experiment, h.experiment_id)
        if h is not None and h.status == "testing" and h.experiment_id
        else None
    )
    if h is not None and h.status != "accepted" and existing is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{h.code} не принята к проверке — проверку создают только из принятой идеи",
        )
    expected = body.expected.strip()
    if h is not None and existing is None and len(expected) < 3:
        # как в мастере проверки: критерий записывается до расчёта (SPEC, «Гипотезы»)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Запишите до расчёта, что подтвердит или опровергнет идею",
        )
    title = (body.title.strip() or f"{body.choice.title or t.title} · {ds.code}")[:512]
    summary = f"{ds.code} · версия {snap.version}"[:512]
    choice = {
        "template": t.key,
        "snapshot_id": snap.id,
        "node": body.node,
        "hypothesis": h.code if h is not None else "",
        **_checked_choice(body.choice, t.key, body.params),
    }
    setup = [*choice["why"][:10]] + (
        [f"Что подтвердит или опровергнет: {expected}"] if expected else []
    )
    try:
        if existing is not None:
            exp = existing
        elif h is not None:
            # идея и её источники переносятся в проверку, идея — «проверяется»
            exp = experiment_from_hypothesis(
                db, h, user.id, title=title, method=t.title, data_summary=summary, setup=setup
            )
            if node is not None:
                exp.methodology_node_id = node.id
            close_open_proposals(
                db, h, user.id
            )  # человек настроил проверку — ждущие предложения Qwen закрыты
        else:
            exp = Experiment(
                code=next_code(db, Experiment.code, "EXP", 3),
                title=title,
                hypothesis=analysis.question(t.key, body.params),
                author_id=user.id,
                method=t.title,
                data_summary=summary,
                methodology_node_id=node.id if node else None,
                setup=[*body.choice.why[:10]],
                results=[],
                limitations=[],
                reproducibility=[],
            )
            db.add(exp)
        exp.status, exp.dataset_snapshot_id = "running", snap.id
        db.flush()
        run = start_run(db, settings, user, t.key, snap.id, body.params, exp.code)
        # первый выбор — config.analysis; все расчёты проверки с их выбором — config.analysis_runs
        config: dict[str, Any] = dict(exp.config or {})
        config.setdefault("analysis", choice)
        before = config.get("analysis_runs")
        config["analysis_runs"] = [
            *(before if isinstance(before, list) else []),
            {**choice, "run_id": run.id},
        ]
        exp.config = config
        if h is not None and existing is None:
            # та же запись, что у проверки, настроенной в мастере: история идеи видит её
            used = run.config.get("params")
            db.add(
                ExperimentProposal(
                    hypothesis_id=h.id,
                    status="approved",
                    title=exp.title,
                    method=t.key,
                    snapshot_id=snap.id,
                    params=dict(used) if isinstance(used, dict) else {},
                    setup=setup[:10],
                    expected=expected,
                    decided_by=user.id,
                    decided_at=datetime.now(UTC),
                    experiment_id=exp.id,
                    run_id=run.id,
                )
            )
    except HTTPException:
        db.rollback()  # проверка без расчёта в реестре не нужна
        raise
    db.commit()
    return LaunchOut(experiment=exp.code, run_id=run.id)


def _actual_net(template: str, params: dict[str, Any]) -> str:
    """Какая сеть реально считается: метод и параметр «Нейросеть», а не подпись карточки."""
    if template == "lab-mlp":
        arch = params.get("architecture") or "mlp"
        return str(arch) if str(arch) in net_catalog.NETS else "mlp"
    return {"predictive-check": "gbm", "rank-agreement": "rank"}.get(template, "")


def _checked_choice(c: Choice, template: str, params: dict[str, Any]) -> dict[str, Any]:
    """Выбор с карточки, сверенный с тем, что посчитается: человек сменил сеть в параметрах —
    в проверке так и написано, «как у авторов» снимается, если сеть уже не их."""
    out = c.model_dump()
    actual = _actual_net(template, params)
    # линейная регрессия авторов считается в быстрой проверке вместе с бустингом
    same = c.net == actual or (c.net == "linear" and actual == "gbm")
    if c.net and actual and not same:
        was, now = net_catalog.NETS.get(c.net), net_catalog.NETS[actual]
        out["why"] = [
            f"Сеть заменена вручную: вместо «{was.title if was else c.net}» — «{now.title}».",
            *out["why"],
        ][:20]
        out.update(edited=True, replaced=c.net, net=actual, as_authors=False, primary=False)
    elif not c.net:
        out["net"] = actual
    return out


# --- «Нейросети»: найденная связь → набор сетей → сравнение ---------------------------------------
# набор сетей проверки связи — карточки рекомендации прогноза (app/services/analysis.py: recommend)
NET_SET = ("lab-mlp:mlp", "lab-mlp:transformer", "predictive-check")
# «держится»: R² на отложенных данных выше перемешанной цели и заметно выше прогноза средним
HOLDS_MIN_R2 = 0.05


def _visible(ds: Dataset, user: User) -> None:
    """Столбцы набора под NDA — только допущенным, как у снимка таблицы (app/api/runs.py)."""
    if ds.access_level == "nda" and user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Файлы датасета под NDA — только для допущенных")


def _scan(db: Session, run_id: int) -> Run:
    run = db.get(Run, run_id)
    if run is None or run.template != "correlation-scan":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет расчёта «Поиск связей» № {run_id}")
    if run.status != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Поиск связей № {run_id} ещё не закончен")
    return run


def _scan_links(run: Run) -> list[dict[str, Any]]:
    links = (run.summary or {}).get("links")
    return [x for x in links if isinstance(x, dict)] if isinstance(links, list) else []


def _fit_net(db: Session, settings: Settings, table: Table, rows: int | None,
             rec: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Параметры сети набора, с которыми расчёт укладывается в лимит метода. Не укладывается —
    меньше испытаний подбора (протокол CR-01 не трогаем), иначе None и причина: сеть пропускается,
    остальные сети набора считаются."""
    t = lib.template(db, rec["template"])
    if t is None:
        return None, "метода нет в библиотеке"
    try:
        checked = check_params(t, rec["params"], table.columns, table.numeric, table.sheets, table.sheet)
    except ParamError as exc:
        return None, str(exc)
    est = resources.estimate(db, settings, t, checked, rows)
    if est.within_limit:
        return rec["params"], ""
    fit = (est.suggestion or {}).get("params")
    if isinstance(fit, dict):
        return fit, (f"{rec['title']}: испытаний подбора — {fit.get('trials')} вместо {checked.get('trials')}, "
                     f"иначе по оценке больше лимита метода {est.limit_min} мин.")
    return None, f"по оценке около {est.minutes:g} мин — больше лимита метода {est.limit_min} мин"


def _link_check(exp: Experiment) -> dict[str, Any] | None:
    lc = (exp.config or {}).get("link_check")
    return lc if isinstance(lc, dict) else None


def net_id(rec: dict[str, Any]) -> str:
    """Как сеть набора называется в выборе: net каталога (mlp, transformer, gbm — быстрая проверка:
    бустинг и линейная) или ключ метода из статьи (у него net каталога может совпасть с встроенной)."""
    return str(rec["key"]) if str(rec["key"]).startswith(lib.PREFIX) else str(rec["net"])


def _check_net_ids(exp: Experiment) -> set[str]:
    """Сети, которые уже считались (или считаются) в проверке связи."""
    runs = (exp.config or {}).get("analysis_runs")
    return {net_id(c) for c in runs if isinstance(c, dict)} if isinstance(runs, list) else set()


def _link_set(
    db: Session, settings: Settings, user: User, scan: Run, a: str, b: str, target: str, node_number: str,
) -> tuple[DatasetSnapshot, Dataset, Table, int | None, MethodologySection | None, list[dict[str, Any]]]:
    """Связь из поиска → данные и все сети набора для неё (и те, что сейчас не запустить)."""
    pair = {a, b}
    if not any({x.get("a"), x.get("b")} == pair for x in _scan_links(scan)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Эта связь не подтвердилась в поиске — проверять сетями нечего")
    if target not in pair:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Предсказываем один из двух показателей связи")
    if scan.dataset_snapshot_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "У поиска связей нет версии данных")
    snap, ds = _snapshot(db, scan.dataset_snapshot_id)
    params = (scan.config or {}).get("params")
    sheet = str(params.get("sheet") or "") if isinstance(params, dict) else ""
    table = snapshot_table(db, settings, snap, user, sheet)  # NDA — только с допуском
    node = _node(db, node_number)
    rows = resources.rows_of(settings, snap, table.sheet)
    try:
        # второй показатель связи — во входах всегда: проверяем именно эту связь
        out = analysis.recommend(table, rows, target, node, library=_library(db),
                                 keep=b if target == a else a)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    # набор: перцептрон, трансформер, бустинг с линейной — и включённые методы из статей
    recs = [r for r in out["recommendations"] if r["key"] in NET_SET or r["key"].startswith(lib.PREFIX)]
    return snap, ds, table, rows, node, recs


def _existing_check(db: Session, snap: DatasetSnapshot, scan: Run, pair: set[str], target: str) -> Experiment | None:
    for old in db.scalars(select(Experiment).where(Experiment.dataset_snapshot_id == snap.id)):
        lc = _link_check(old)
        if (lc is not None and lc.get("scan_run") == scan.id and {lc.get("a"), lc.get("b")} == pair
                and lc.get("target") == target):
            return old
    return None


# что ставить галочкой по умолчанию: перцептрон лаборатории и быстрая проверка без нейросети;
# трансформер — по желанию: считается в разы дольше
RECOMMENDED = ("mlp", "gbm")


class LinkNetsIn(BaseModel):
    scan_run: int
    a: str = Field(min_length=1, max_length=512)
    b: str = Field(min_length=1, max_length=512)
    target: str = Field(min_length=1, max_length=512)
    node: str = ""


@router.post("/link-nets")
def link_nets(
    body: LinkNetsIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Из чего выбирать перед проверкой связи: какие сети есть, сколько каждая считается,
    что уже считалось в этой проверке. Ничего не запускает."""
    scan = _scan(db, body.scan_run)
    snap, _, table, rows, _, recs = _link_set(db, settings, user, scan, body.a, body.b, body.target, body.node)
    existing = _existing_check(db, snap, scan, {body.a, body.b}, body.target)
    done = _check_net_ids(existing) if existing else set()
    nets = []
    for r in recs:
        nid = net_id(r)
        minutes, note = None, ""
        if r["runnable"]:
            params_fit, note = _fit_net(db, settings, table, rows, r)
            t = lib.template(db, r["template"])
            if params_fit is not None and t is not None:
                checked = check_params(t, params_fit, table.columns, table.numeric, table.sheets, table.sheet)
                minutes = resources.estimate(db, settings, t, checked, rows).minutes
        nets.append({
            "id": nid, "net": r["net"], "title": r["title"], "minutes": minutes, "note": note,
            "runnable": bool(r["runnable"]) and minutes is not None,
            "warnings": [*r["warnings"], *([note] if r["runnable"] and minutes is None and note else [])],
            "recommended": nid in RECOMMENDED, "done": nid in done,
        })
    return {"nets": nets, "existing": existing.code if existing else None,
            "existing_status": existing.status if existing else None}


@router.post("/link-check", response_model=LinkCheckOut, status_code=status.HTTP_201_CREATED)
def link_check(
    body: LinkCheckIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
) -> LinkCheckOut:
    """Одна проверка EXP-NNN и по расчёту на каждую выбранную сеть — одним действием: не встал
    хоть один расчёт — нет ни проверки, ни расчётов. Связь должна быть подтверждена поиском.
    Проверка этой связи уже есть — выбранные сети, которых в ней ещё не было, добавляются к ней."""
    scan = _scan(db, body.scan_run)
    pair = {body.a, body.b}
    snap, ds, table, rows, node, all_recs = _link_set(db, settings, user, scan, body.a, body.b,
                                                      body.target, body.node)
    other = body.b if body.target == body.a else body.a
    existing = _existing_check(db, snap, scan, pair, body.target)
    recs = [r for r in all_recs if r["runnable"]]
    if body.nets:
        unknown = sorted(set(body.nets) - {net_id(r) for r in all_recs})
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Таких сетей нет в наборе: {', '.join(unknown)}")
        recs = [r for r in recs if net_id(r) in body.nets]
    if existing is not None:
        if existing.status == "done":
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Проверка {existing.code} уже завершена — новые сети к ней не добавить")
        before = _check_net_ids(existing)
        recs = [r for r in recs if net_id(r) not in before]
        if not recs:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Эту связь уже проверяют сетями: {existing.code}")
    if not recs:
        why = "; ".join(w for r in all_recs if not body.nets or net_id(r) in body.nets for w in r["warnings"])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Ни одну выбранную сеть не запустить: {why or 'мало данных'}")
    planned, skipped = [], []
    for r in recs:
        params_fit, note = _fit_net(db, settings, table, rows, r)
        if params_fit is None:
            skipped.append({"net": r["net"], "title": r["title"], "reason": note})
        else:
            planned.append((r, params_fit, note))
    if not planned:
        why = "; ".join(f"{x['title']} — {x['reason']}" for x in skipped)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Ни одна выбранная сеть не укладывается в лимит: {why}")
    nets = ", ".join(r["title"] for r, _, _ in planned)
    holds = f"{HOLDS_MIN_R2:.2f}".replace(".", ",")
    try:
        if existing is None:
            exp = Experiment(
                code=next_code(db, Experiment.code, "EXP", 3),
                title=f"Связь «{body.a}» — «{body.b}»: проверка сетями · {ds.code}"[:512],
                hypothesis=(f"Предсказывают ли остальные показатели «{body.target}» на данных, которых не было "
                            "в обучении, лучше перемешанной цели — у каждой выбранной сети? Связь "
                            f"«{other}» — «{body.target}» подтвердилась поиском связей (расчёт № {scan.id}); "
                            "здесь — держится ли она у разных моделей."),
                author_id=user.id,
                method=f"Сети: {nets}"[:512],
                data_summary=f"{ds.code} · версия {snap.version}"[:512],
                methodology_node_id=node.id if node else None,
                setup=[
                    f"Связь найдена и подтверждена на отложенной части: расчёт «Поиск связей» № {scan.id}.",
                    f"Каждая сеть предсказывает «{body.target}» по остальным показателям по протоколу CR-01: "
                    "разбиения, плацебо на перемешанной цели, сравнение с линейной моделью.",
                    f"Связь держится у сети, если R² на отложенных данных выше перемешанной цели и выше {holds}.",
                    *[note for _, _, note in planned if note],
                ],
                results=[],
                limitations=["Связь — не причина: предсказуемость не говорит, что из чего следует.",
                             *[f"{x['title']} не запускалась: {x['reason']}." for x in skipped]],
                reproducibility=[],
                status="running",
                dataset_snapshot_id=snap.id,
            )
            db.add(exp)
            db.flush()
        else:  # добавить сети к той же проверке: сравнение сетей — в одной таблице
            exp = existing
            exp.method = f"{exp.method}, {nets}"[:512]
            exp.setup = [*exp.setup, f"Добавлены сети: {nets}.", *[note for _, _, note in planned if note]]
            exp.limitations = [*exp.limitations, *[f"{x['title']} не запускалась: {x['reason']}." for x in skipped]]
            exp.status = "running"
        runs, choices = [], []
        for r, params_fit, _ in planned:
            run = start_run(db, settings, user, r["template"], snap.id, params_fit, exp.code)
            runs.append(run)
            choice = Choice(key=r["key"], title=r["title"], why=r["why"][:20], primary=r["primary"],
                            net=r["net"], task="predict")
            choices.append({"template": r["template"], "snapshot_id": snap.id, "node": body.node,
                            "hypothesis": "", **_checked_choice(choice, r["template"], params_fit),
                            "run_id": run.id})
        cfg = dict(exp.config or {})
        old_lc = _link_check(exp) or {}
        prev = cfg.get("analysis_runs")
        old_runs: list[Any] = prev if isinstance(prev, list) else []
        exp.config = {
            **cfg,
            "link_check": {"scan_run": scan.id, "a": body.a, "b": body.b, "target": body.target,
                           "skipped": [*(old_lc.get("skipped") or []), *skipped]},
            "analysis": cfg.get("analysis") or choices[0],
            "analysis_runs": [*old_runs, *choices],
        }
    except HTTPException:
        db.rollback()  # набор без одной из сетей — не тот набор: ни проверки, ни расчётов
        raise
    db.commit()
    return LinkCheckOut(experiment=exp.code, run_ids=[r.id for r in runs], added=existing is not None)


NET_ORDER = ("mlp", "transformer", "gbm", "linear")


def _skipped(lc: dict[str, Any]) -> list[dict[str, Any]]:
    """Сети набора, которые не запускались (не уложились в лимит), — с причиной; быстрая проверка —
    это и бустинг, и линейная."""
    out = []
    for x in lc.get("skipped") or []:
        if not isinstance(x, dict):
            continue
        for net in (("gbm", "linear") if x.get("net") == "gbm" else (str(x.get("net") or ""),)):
            title = net_catalog.NETS[net].title if net in net_catalog.NETS else net
            out.append({"run_id": None, "status": "skipped", "net": net, "title": title, "r2": None,
                        "placebo": None, "holds": None, "reason": str(x.get("reason") or "")})
    return out


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _net_results(run: Run) -> list[dict[str, Any]]:
    """Итог расчёта по сетям: R² на отложенных данных и на перемешанной цели (плацебо)."""
    s = run.summary or {}
    params = (run.config or {}).get("params")
    rows: list[tuple[str, float | None, float | None]]
    if run.template == "lab-mlp":
        arch = str(params.get("architecture") or "mlp") if isinstance(params, dict) else "mlp"
        rows = [(arch, _num(s.get("mlp_r2_mean")), _num(s.get("placebo_r2_max")))]
    elif run.template.startswith(lib.PREFIX):  # метод из статьи: протокол пишет те же итоги
        title = str(s.get("method") or run.template.removeprefix(lib.PREFIX))
        r2m, plm = _num(s.get("model_r2_mean")), _num(s.get("placebo_r2_max"))
        holds = None
        if run.status == "done" and r2m is not None:
            holds = r2m > HOLDS_MIN_R2 and (plm is None or r2m > plm)
        return [{"run_id": run.id, "status": run.status, "net": run.template, "title": title, "r2": r2m,
                 "placebo": plm, "holds": holds}]
    elif run.template == "predictive-check":
        r2 = s.get("r2_mean")
        pl = s.get("placebo_max")
        r2d = r2 if isinstance(r2, dict) else {}
        pld = pl if isinstance(pl, dict) else {}
        rows = [("gbm", _num(r2d.get("LightGBM")), _num(pld.get("LightGBM"))),
                ("linear", _num(r2d.get("Линейная (Ridge)")), _num(pld.get("Линейная (Ridge)")))]
    else:
        return []
    out = []
    for net, r2v, plv in rows:
        holds = None
        if run.status == "done" and r2v is not None:
            holds = r2v > HOLDS_MIN_R2 and (plv is None or r2v > plv)
        title = net_catalog.NETS[net].title if net in net_catalog.NETS else net
        out.append({"run_id": run.id, "status": run.status, "net": net, "title": title, "r2": r2v,
                    "placebo": plv, "holds": holds})
    return out


def scan_method(run: Run) -> str:
    """Способ поиска связей расчёта; у расчётов до выбора способа — rank."""
    params = (run.config or {}).get("params")
    return str(params.get("method") or "rank") if isinstance(params, dict) else "rank"


@router.get("/links")
def links(
    snapshot_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    method: str = "",
) -> dict[str, Any]:
    """Последний поиск связей по версии данных (method — этим способом; пусто — любым) и проверки
    его связей сетями — вкладка «Нейросети». scans — последний поиск каждым способом."""
    snap, ds = _snapshot(db, snapshot_id)
    _visible(ds, user)
    latest: dict[str, Run] = {}
    for r in db.scalars(select(Run).where(Run.template == "correlation-scan", Run.dataset_snapshot_id == snap.id)
                        .order_by(Run.id.desc())):
        latest.setdefault(scan_method(r), r)
    scan = latest.get(method) if method else max(latest.values(), key=lambda r: r.id, default=None)
    checks = []
    if scan is not None:
        exps = db.scalars(select(Experiment).where(Experiment.dataset_snapshot_id == snap.id)
                          .order_by(Experiment.id))
        for exp in exps:
            lc = _link_check(exp)
            if lc is None or lc.get("scan_run") != scan.id:
                continue
            nets = [n for r in db.scalars(select(Run).where(Run.experiment_id == exp.id).order_by(Run.id))
                    for n in _net_results(r)]
            nets += _skipped(lc)
            nets.sort(key=lambda n: NET_ORDER.index(n["net"]) if n["net"] in NET_ORDER else 99)
            finished = [n for n in nets if n["holds"] is not None]
            checks.append({"experiment": exp.code, "a": lc.get("a"), "b": lc.get("b"),
                           "target": lc.get("target"), "nets": nets,
                           "held": sum(1 for n in finished if n["holds"]), "finished": len(finished),
                           "total": sum(1 for n in nets if n["status"] != "skipped")})
    s = scan.summary if scan is not None and isinstance(scan.summary, dict) else {}
    params = (scan.config or {}).get("params") if scan is not None else None
    scan_out = None
    if scan is not None:
        scan_out = {
            "run_id": scan.id, "status": scan.status, "message": scan.message,
            "group": params.get("group", "") if isinstance(params, dict) else "",
            **{k: s.get(k) for k in ("unit", "rows_find", "rows_confirm", "pairs", "found", "confirmed",
                                     "panel_hint", "not_confirmed_total", "links_total")},
            "links": _scan_links(scan),
            "method": scan_method(scan),
        }

    def brief(r: Run) -> dict[str, Any]:
        s = r.summary if isinstance(r.summary, dict) else {}
        return {"method": scan_method(r), "run_id": r.id, "status": r.status,
                "confirmed": s.get("confirmed"), "pairs": s.get("pairs")}

    return {
        "snapshot": {"id": snap.id, "dataset": ds.code, "title": ds.title, "version": snap.version},
        "scan": scan_out,
        "checks": checks,
        "scans": [brief(r) for r in sorted(latest.values(), key=lambda r: r.id)],
    }
