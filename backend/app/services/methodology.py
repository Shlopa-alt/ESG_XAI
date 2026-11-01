"""Правило домена 2: изменение методологии — только через CR с основанием и одобрением."""

import difflib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ChangeRequest,
    CrBasis,
    Experiment,
    KbRef,
    MethodologySection,
    MethodologyVersion,
    Review,
)
from app.services.experiments import DomainError


def valid_bases(db: Session, cr: ChangeRequest) -> list[str]:
    """Основания CR, которые годятся для принятия (описание каждого)."""
    ok = []
    for basis in db.scalars(select(CrBasis).where(CrBasis.cr_id == cr.id)):
        if basis.basis_type == "experiment" and basis.experiment_id is not None:
            exp = db.get(Experiment, basis.experiment_id)
            if exp is not None and exp.status == "done":
                ok.append(f"эксперимент {exp.code}")
        elif basis.kb_ref_id is not None:
            ref = db.get(KbRef, basis.kb_ref_id)
            if ref is None:
                continue
            if basis.basis_type == "kb_fact" and ref.kind == "fact" and ref.quote.strip():
                ok.append(f"факт KBRAG {ref.kbrag_id}")
            if basis.basis_type == "kb_article" and ref.kind == "article" and ref.doi.strip():
                ok.append(f"статья KBRAG {ref.doi}")
    return ok


def has_approval(db: Session, cr: ChangeRequest) -> bool:
    return (
        db.scalar(
            select(Review.id).where(
                Review.target_type == "cr", Review.target_id == cr.id, Review.verdict == "approve"
            )
        )
        is not None
    )


def why_not_acceptable(db: Session, cr: ChangeRequest) -> list[str]:
    reasons = []
    if not valid_bases(db, cr):
        reasons.append(
            "нет основания: нужен завершённый эксперимент, проверенный факт KBRAG с цитатой "
            "или статья KBRAG с DOI"
        )
    if not has_approval(db, cr):
        reasons.append("нет одобряющей рецензии")
    return reasons


def current_version(db: Session) -> MethodologyVersion | None:
    return db.scalars(
        select(MethodologyVersion).order_by(MethodologyVersion.id.desc()).limit(1)
    ).first()


def next_version(version: str) -> str:
    major, _, minor = version.partition(".")
    return f"{major}.{int(minor or 0) + 1}"


def snapshot(db: Session) -> dict[str, dict[str, str]]:
    nodes = list(db.scalars(select(MethodologySection)))
    number = {n.id: n.number for n in nodes}
    return {
        n.number: {"title": n.title, "content": n.content, "stability": n.stability, "kind": n.kind,
                   "parent": number.get(n.parent_id, "") if n.parent_id else ""}
        for n in nodes
    }


# Что можно добавить под узлом каждого вида; None — корень методики
CHILD_KINDS: dict[str | None, tuple[str, ...]] = {
    None: ("direction", "section"),
    "direction": ("variant", "task", "section"),
    "variant": ("task", "section"),
    "task": ("section",),
    "section": (),
}
PREFIX = {"direction": "Н", "variant": "В", "task": "З", "section": "Р"}


def child_number(db: Session, parent: MethodologySection | None, kind: str) -> tuple[str, int]:
    """Номер и позиция нового узла: следующий по порядку среди соседей того же вида."""
    prefix = "О" if parent is None and kind == "section" else PREFIX[kind]
    base = f"{parent.number}." if parent is not None else ""
    pid = parent.id if parent is not None else None
    same_parent = (MethodologySection.parent_id.is_(None) if pid is None
                   else MethodologySection.parent_id == pid)
    siblings = db.scalars(select(MethodologySection).where(same_parent))
    nums = [int(m.group(1)) for n in siblings
            if (m := re.fullmatch(re.escape(base + prefix) + r"(\d+)", n.number))]
    n = max(nums, default=0) + 1
    return f"{base}{prefix}{n}", n


def accept(db: Session, cr: ChangeRequest, user_id: int) -> MethodologyVersion:
    """Принять CR: проверка правила, новый текст раздела, раздел — устойчив, новая версия."""
    reasons = why_not_acceptable(db, cr)
    if reasons:
        raise DomainError("CR нельзя принять: " + "; ".join(reasons))
    parent = db.get(MethodologySection, cr.section_id) if cr.section_id else None
    if cr.action == "add":
        # новый узел — задание, вариант, раздел — под указанным (или в корне методики)
        number, position = child_number(db, parent, cr.new_kind)
        db.add(MethodologySection(number=number, title=cr.new_title, content=cr.proposed_content,
                                  stability="stable", kind=cr.new_kind,
                                  parent_id=parent.id if parent else None, position=position))
        db.flush()
    else:
        if parent is None:
            raise DomainError("Узел CR не найден")
        if cr.proposed_content.strip():
            parent.content = cr.proposed_content
        parent.stability = "stable"
    cur = current_version(db)
    version = MethodologyVersion(
        version=next_version(cur.version if cur else "0.0"),
        sections_content=snapshot(db),
        notes=f"{cr.code}: {cr.title}",
        created_by=user_id,
    )
    cr.status = "accepted"
    cr.target_version = version.version
    db.add(version)
    return version


def diff(old: dict[str, dict[str, str]], new: dict[str, dict[str, str]]) -> list[dict[str, object]]:
    """Изменения по разделам между двумя снимками версий."""
    out: list[dict[str, object]] = []
    for number in sorted(set(old) | set(new)):
        a, b = old.get(number, {}), new.get(number, {})
        if a == b:
            continue
        lines = list(
            difflib.unified_diff(
                a.get("content", "").splitlines(), b.get("content", "").splitlines(),
                lineterm="", n=0,
            )
        )[2:]
        out.append({
            "number": number,
            "title": b.get("title") or a.get("title", ""),
            "stability": [a.get("stability"), b.get("stability")],
            "lines": lines,
        })
    return out
