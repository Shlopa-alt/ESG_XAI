"""CR от Qwen по одобренному отчёту об эксперименте: контекст, проверка черновика, создание.

Рецензент одобрил отчёт, в котором есть «Предложение для методики» (или исследователь нажал
«Предложить CR»), — платформа ставит задачу Qwen `cr`. Qwen видит отчёт, задание методики, к
которому привязан эксперимент, и разделы, что на него действуют, и решает: менять ли методику и
что именно — править узел или добавить под ним новый. Черновик проверяется здесь: узел из
допустимых, вид нового узла по CHILD_KINDS, текст не пустой. Основание — сам эксперимент.
CR создаётся «предложенным»: дальше обычный путь — рецензия и решение owner (правило 2).
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ChangeRequest,
    CrBasis,
    Experiment,
    ExperimentReport,
    MethodologySection,
    QwenJob,
    User,
)
from app.services.codes import next_code
from app.services.methodology import CHILD_KINDS
from app.services.qwen_reports import check_numbers

OPEN = ("proposed", "review")


def targets(db: Session, exp: Experiment | None) -> list[MethodologySection]:
    """Что CR по эксперименту может менять: узлы от направления до задания эксперимента, их разделы
    и общие разделы методики. Эксперимент без задания — только общие разделы."""
    nodes = {n.id: n for n in db.scalars(select(MethodologySection))}
    chain, cur = [], nodes.get(exp.methodology_node_id) if exp and exp.methodology_node_id else None
    while cur is not None:
        chain.append(cur)
        cur = nodes.get(cur.parent_id) if cur.parent_id else None
    ids = {c.id for c in chain}
    sections = [n for n in nodes.values() if n.kind == "section" and (n.parent_id is None or n.parent_id in ids)]
    return chain[::-1] + sorted(sections, key=lambda s: s.number)


def context(db: Session, report: ExperimentReport) -> dict[str, Any]:
    exp = db.get(Experiment, report.experiment_id)
    number = {n.id: n.number for n in db.scalars(select(MethodologySection))}
    out = []
    for n in targets(db, exp):
        crs = db.scalars(select(ChangeRequest).where(ChangeRequest.section_id == n.id,
                                                     ChangeRequest.status.in_(OPEN)))
        out.append({"number": n.number, "kind": n.kind, "title": n.title, "content": n.content,
                    "parent": number.get(n.parent_id, "") if n.parent_id else "",
                    "can_add": list(CHILD_KINDS[n.kind]), "open_crs": [f"{c.code}: {c.title}" for c in crs]})
    e = (report.facts or {}).get("experiment", {})
    return {"report_id": report.id, "experiment": {"code": e.get("code"), "title": e.get("title"),
                                                   "node": e.get("node"), "hypothesis": e.get("hypothesis"),
                                                   "setup": e.get("setup") or []},
            "version": report.version, "sections": report.sections or {}, "kpis": (report.facts or {}).get("kpis", []),
            "targets": out}


def problems(db: Session, cr: ChangeRequest) -> str:
    """Что проверить в черновике Qwen: числа не из расчёта, укороченный текст узла, незавершённый эксперимент."""
    report = db.get(ExperimentReport, cr.report_id) if cr.report_id else None
    if report is None:
        return ""
    out = []
    nums = check_numbers(report.facts or {}, {"text": f"{cr.title} {cr.description} {cr.proposed_content}"})
    if nums:
        out.append(nums)
    node = db.get(MethodologySection, cr.section_id) if cr.section_id else None
    if cr.action == "edit" and node is not None and len(cr.proposed_content) < 0.8 * len(node.content):
        out.append("новый текст узла заметно короче прежнего — не потерялось ли что-то из него")
    exp = db.get(Experiment, report.experiment_id)
    if exp is not None and exp.status != "done":
        out.append(f"основание {exp.code} станет годным, когда эксперимент будет завершён")
    return "; ".join(out)


def pending_job(db: Session, report_id: int) -> QwenJob | None:
    return db.scalar(select(QwenJob).where(QwenJob.kind == "cr", QwenJob.status.in_(("queued", "running")))
                     .where(QwenJob.payload["report"].as_integer() == report_id))


def last_job(db: Session, report_id: int) -> QwenJob | None:
    return db.scalars(select(QwenJob).where(QwenJob.kind == "cr", QwenJob.payload["report"].as_integer() == report_id)
                      .order_by(QwenJob.id.desc()).limit(1)).first()


def for_report(db: Session, report_id: int) -> ChangeRequest | None:
    return db.scalar(select(ChangeRequest).where(ChangeRequest.report_id == report_id))


LATIN = str.maketrans({"H": "Н", "B": "В", "P": "Р", "O": "О", "h": "Н", "b": "В", "p": "Р", "o": "О"})


def node_number(raw: str) -> str:
    """Номер узла от модели: латинские двойники букв (H2 вместо Н2) и цифра 3 вместо «З» — в кириллицу."""
    return re.sub(r"(^|\.)3(?=\d)", r"\1З", raw.strip().translate(LATIN))


def create_from_result(db: Session, job: QwenJob, result: dict[str, Any]) -> tuple[ChangeRequest | None, str]:
    """CR из ответа Qwen или (None, почему его нет)."""
    report = db.get(ExperimentReport, int((job.payload or {}).get("report") or 0))
    if report is None or report.status != "approved":
        return None, "Отчёт не одобрен — CR не нужен"
    if (old := for_report(db, report.id)) is not None:
        return None, f"По этому отчёту уже есть {old.code}"
    reason = str(result.get("reason") or "").strip()
    if result.get("decision") != "change":
        return None, f"Qwen: менять методику по этому отчёту не нужно — {reason or 'без пояснения'}"
    exp = db.get(Experiment, report.experiment_id)
    allowed = {n.number: n for n in targets(db, exp)}
    node = allowed.get(node_number(str(result.get("section") or "")))
    action = result.get("action")
    title = str(result.get("title") or "").strip()[:512]
    content = str(result.get("proposed_content") or "").strip()
    new_kind, new_title = str(result.get("new_kind") or ""), str(result.get("new_title") or "").strip()[:512]
    why = []
    if node is None:
        why.append(f"узел «{result.get('section')}» не из задания эксперимента")
    if action not in ("edit", "add"):
        why.append("нет действия edit или add")
    if action == "add" and node is not None and new_kind not in CHILD_KINDS[node.kind]:
        why.append(f"под «{node.number}» нельзя добавить «{new_kind}»")
    elif action == "add" and new_kind != "section":
        # структуру методики (направления, варианты, задания) задают люди; Qwen добавляет правила — разделы
        why.append("Qwen добавляет только разделы — направления, варианты и задания предлагают люди")
    if action == "add" and len(new_title) < 3:
        why.append("нет заголовка нового узла")
    if len(title) < 3 or not content:
        why.append("нет заголовка или текста CR")
    if action == "edit" and node is not None and node.kind != "section":
        # описание направления, варианта, задания правят люди; правило под ними — новым разделом
        why.append(f"Qwen правит только разделы, а «{node.number}» — не раздел: правило — новым разделом под ним")
    if why or node is None:
        return None, "Черновик CR от Qwen отброшен: " + "; ".join(why)
    if action == "edit":
        # Qwen присылает добавку к разделу — платформа дописывает её к прежнему тексту, ничего не теряя
        old = node.content.strip()
        if old and content.startswith(old[:80]):
            content = content[len(old):].strip() if content.startswith(old) else content
        if not content or content == old:
            return None, "Черновик CR от Qwen отброшен: текст раздела не меняется"
        if not (old and content.startswith(old[:80])):
            content = f"{old}\n\n{content}" if old else content
    user = db.get(User, report.reviewed_by) if report.reviewed_by else None
    e = (report.facts or {}).get("experiment", {})
    cr = ChangeRequest(
        code=next_code(db, ChangeRequest.code, "CR", 2), section_id=node.id, action=action,
        new_kind=new_kind if action == "add" else "", new_title=new_title if action == "add" else "",
        title=title, status="proposed", author_id=None, proposed_content=content,
        description=(str(result.get("description") or "").strip()[:3000]
                     + f"\n\nЧерновик Qwen по отчёту {e.get('code', '')} v{report.version}"
                     + (f", одобренному {user.login}" if user else "") + ".").strip(),
        source="qwen", report_id=report.id, qwen_job_id=job.id)
    db.add(cr)
    db.flush()
    if exp is not None:
        db.add(CrBasis(cr_id=cr.id, basis_type="experiment", experiment_id=exp.id))
    cr.problems = problems(db, cr)
    return cr, ""
