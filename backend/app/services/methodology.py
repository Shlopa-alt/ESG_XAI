"""Правило домена 2: изменение методологии — только через CR с основанием и одобрением."""

import difflib

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
    return {
        s.number: {"title": s.title, "content": s.content, "stability": s.stability}
        for s in db.scalars(select(MethodologySection).order_by(MethodologySection.number))
    }


def accept(db: Session, cr: ChangeRequest, user_id: int) -> MethodologyVersion:
    """Принять CR: проверка правила, новый текст раздела, раздел — устойчив, новая версия."""
    reasons = why_not_acceptable(db, cr)
    if reasons:
        raise DomainError("CR нельзя принять: " + "; ".join(reasons))
    section = db.get(MethodologySection, cr.section_id)
    if section is None:
        raise DomainError("Раздел CR не найден")
    if cr.proposed_content.strip():
        section.content = cr.proposed_content
    section.stability = "stable"
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
