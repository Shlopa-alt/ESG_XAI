"""Отчёты Qwen по экспериментам (app/models/report_doc.py): факты расчёта, контекст, сверка чисел.

Запуск завершился (или исследователь нажал «Сформировать отчёт») — платформа ставит задачу Qwen
`report`. Факты (постановка, данные, параметры, воспроизводимость, ключевые цифры и графики)
собираются здесь из эксперимента и запуска и замораживаются в отчёте; Qwen пишет только текст.
Числа в тексте сверяются с фактами: число, которого в расчёте нет, попадает в problems.
"""

import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    ExperimentProposal,
    ExperimentReport,
    Hypothesis,
    HypothesisRef,
    KbRef,
    MethodologySection,
    QwenJob,
    Run,
)
from app.services.run_templates import TEMPLATES

NUM = re.compile(r"[−-]?\d+(?:[.,]\d+)?")
SECTION_KEYS = ("summary", "verdict", "verdict_reason", "interpretation", "meaning", "methodology",
                "limitations", "next")


def _node_label(db: Session, nid: int | None) -> str:
    node = db.get(MethodologySection, nid) if nid else None
    return f"{node.number} {node.title}" if node else ""


def facts(db: Session, exp: Experiment, run: Run | None) -> dict[str, Any]:
    h = db.scalar(select(Hypothesis).where(Hypothesis.experiment_id == exp.id))
    proposal = db.scalar(select(ExperimentProposal).where(ExperimentProposal.experiment_id == exp.id))
    snap = db.get(DatasetSnapshot, run.dataset_snapshot_id) if run and run.dataset_snapshot_id else None
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    t = TEMPLATES.get(run.template) if run else None
    report = exp.report or {}
    from app.api.runs import _reproducible  # здесь — чтобы не было циклического импорта

    return {
        "experiment": {"code": exp.code, "title": exp.title, "hypothesis": exp.hypothesis, "direction": exp.direction,
                       "node": _node_label(db, exp.methodology_node_id), "method": exp.method,
                       "data_summary": exp.data_summary, "setup": list(exp.setup or []),
                       "limitations": list(exp.limitations or []), "conclusion": exp.conclusion,
                       "outcome": exp.outcome or ""},
        "hypothesis": {"code": h.code, "title": h.title, "statement": h.statement} if h else None,
        "expected": proposal.expected if proposal else "",
        "run": ({"id": run.id, "template": run.template, "template_title": t.title if t else run.template,
                 "params": (run.config or {}).get("params", {}), "seeds": run.seeds or {},
                 "runner_commit": run.runner_commit, "python": run.python, "env_lock_sha256": run.env_lock_sha256,
                 "dataset": ds.code if ds else "", "snapshot_version": snap.version if snap else "",
                 "dataset_sha256": snap.sha256 if snap else "", "rows": snap.row_count if snap else None,
                 "summary": run.summary or {}, "started_at": run.started_at.isoformat() if run.started_at else "",
                 "finished_at": run.finished_at.isoformat() if run.finished_at else "",
                 "reproducible": _reproducible(run)[0]} if run else {}),
        "kpis": list(report.get("kpis") or []),
        "charts": list(report.get("charts") or []),
        "frozen_at": datetime.now(UTC).isoformat(),
    }


def context(db: Session, report: ExperimentReport) -> dict[str, Any]:
    """Что нужно Qwen: факты, задание методики с разделами, опоры гипотезы."""
    exp = db.get(Experiment, report.experiment_id)
    nodes = {n.id: n for n in db.scalars(select(MethodologySection))}
    chain, cur = [], nodes.get(exp.methodology_node_id) if exp and exp.methodology_node_id else None
    while cur is not None:
        chain.append(cur)
        cur = nodes.get(cur.parent_id) if cur.parent_id else None
    ids = {c.id for c in chain}
    sections = [n for n in nodes.values() if n.kind == "section" and (n.parent_id is None or n.parent_id in ids)]
    h = db.scalar(select(Hypothesis).where(Hypothesis.experiment_id == report.experiment_id))
    refs = list(db.scalars(select(KbRef).join(HypothesisRef, HypothesisRef.kb_ref_id == KbRef.id)
                           .where(HypothesisRef.hypothesis_id == h.id))) if h else []
    return {
        "report_id": report.id, "facts": report.facts,
        "task": [{"number": c.number, "title": c.title, "content": c.content} for c in chain[::-1]],
        "sections": [{"number": s.number, "title": s.title, "content": s.content} for s in sections],
        "refs": [{"title": r.title, "quote": r.quote} for r in refs],
    }


def _numbers(text: str) -> set[str]:
    out = set()
    for m in NUM.findall(text):
        v = m.replace("−", "-").replace(",", ".")
        try:
            out.add(f"{abs(float(v)):.2f}")
        except ValueError:
            continue
    return out


def check_numbers(fact: dict[str, Any], sections: dict[str, Any]) -> str:
    """Дробные числа текста (0,27, 3,5 %), которых нет в фактах расчёта, — повод проверить."""
    known = _numbers(json.dumps(fact, ensure_ascii=False))
    text = json.dumps({k: v for k, v in sections.items() if k != "verdict"}, ensure_ascii=False)
    suspect = sorted({m for m in re.findall(r"[−-]?\d+[.,]\d+", text)
                      if f"{abs(float(m.replace('−', '-').replace(',', '.'))):.2f}" not in known})
    return f"Чисел нет в расчёте: {', '.join(suspect[:10])} — проверьте текст" if suspect else ""


def clean_sections(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in SECTION_KEYS:
        v = raw.get(k)
        if k in ("interpretation", "limitations", "next"):
            out[k] = [str(x).strip()[:1500] for x in (v or []) if str(x).strip()][:8]
        elif k == "verdict":
            out[k] = v if v in ("confirmed", "rejected", "inconclusive") else "inconclusive"
        else:
            out[k] = str(v or "").strip()[:3000]
    return out


def new_report(db: Session, exp: Experiment, run: Run | None) -> ExperimentReport:
    """Черновик отчёта с замороженными фактами; текст допишет Qwen."""
    version = (db.scalar(select(func.max(ExperimentReport.version)).where(
        ExperimentReport.experiment_id == exp.id)) or 0) + 1
    r = ExperimentReport(experiment_id=exp.id, run_id=run.id if run else None, version=version, status="draft",
                         facts=facts(db, exp, run), sections={})
    db.add(r)
    db.flush()
    return r


def apply_result(db: Session, job: QwenJob, result: dict[str, Any]) -> ExperimentReport | None:
    r = db.get(ExperimentReport, int((job.payload or {}).get("report") or 0))
    if r is None or r.status != "draft":
        return None
    r.sections = clean_sections(result.get("sections") or {})
    r.qwen_job_id = job.id
    r.problems = check_numbers(r.facts, r.sections)
    return r
