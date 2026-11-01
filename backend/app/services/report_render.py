"""Отчёт по эксперименту в Word и PDF: одни и те же разделы, графики — PNG из matplotlib.

Графики повторяют страницу эксперимента (frontend/src/components/Charts.tsx): «bars» —
горизонтальные столбцы по категориям, до трёх серий палитры --series-1..3, линия отсчёта;
«ranges» — отрезок min…max и точка-среднее. Шрифт — DejaVu (кириллица).
"""

import io
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a"]  # как --series-1..3 на странице эксперимента
TEXT, MUTED, GRID = "#17201b", "#5a6b62", "#d9dfdb"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
VERDICT = {"confirmed": "гипотеза подтверждена", "rejected": "гипотеза отклонена",
           "inconclusive": "результат неоднозначен"}
STATUS = {"draft": "черновик Qwen", "review": "на рецензии", "approved": "одобрен рецензентом",
          "rejected": "отклонён рецензентом"}


def chart_png(spec: dict[str, Any]) -> bytes:
    """График отчёта в PNG (150 dpi)."""
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
                         "axes.labelcolor": TEXT, "xtick.color": MUTED, "ytick.color": TEXT})
    if spec.get("kind") == "ranges":
        rows = spec.get("rows") or []
        fig, ax = plt.subplots(figsize=(6.6, 0.45 * len(rows) + 1.0))
        for i, r in enumerate(rows):
            ax.plot([r["min"], r["max"]], [i, i], color=PALETTE[0], linewidth=2, solid_capstyle="round")
            ax.plot([r["mean"]], [i], "o", color=PALETTE[0], markersize=6, markeredgecolor="white")
        ax.set_yticks(range(len(rows)), [str(r["name"])[:48] for r in rows])
    else:
        cats = spec.get("categories") or []
        series = (spec.get("series") or [])[:3]
        h = 0.8 / max(1, len(series))
        fig, ax = plt.subplots(figsize=(6.6, 0.5 * len(cats) * max(1, len(series)) * 0.6 + 1.2))
        for j, s in enumerate(series):
            ys = [i - 0.4 + h * (j + 0.5) for i in range(len(cats))]
            ax.barh(ys, s["values"], height=h * 0.9, color=PALETTE[j], label=s["name"])
        ax.set_yticks(range(len(cats)), [str(c)[:48] for c in cats])
        if len(series) > 1:  # легенда — под графиком, чтобы не закрывать столбцы
            ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16 if spec.get("unit") else -0.08),
                      ncol=len(series), frameon=False, fontsize=8)
    ref = spec.get("reference")
    if ref:
        ax.axvline(ref["value"], color=MUTED, linewidth=1, linestyle="--")
    ax.invert_yaxis()
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if spec.get("unit"):
        ax.set_xlabel(spec["unit"])
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


def blocks(r: dict[str, Any]) -> list[tuple[str, Any]]:
    """Отчёт как последовательность блоков: ("h1"|"h2"|"p"|"list"|"kv"|"kpis"|"chart", данные)."""
    f, s = r["facts"], r["sections"]
    e, run, h = f.get("experiment", {}), f.get("run", {}), f.get("hypothesis") or {}
    out: list[tuple[str, Any]] = [
        ("title", f"Отчёт об эксперименте {e.get('code', '')} · версия {r['version']}"),
        ("p", e.get("title", "")),
        ("muted", f"Статус: {STATUS.get(r['status'], r['status'])}"
                  + (f" ({r['reviewer']})" if r.get("reviewer") else "")
                  + f". Текст интерпретации подготовила Qwen3-14B по данным расчёта; цифры, таблицы и графики — "
                    f"из run.json запуска №{run.get('id', '?')}."),
        ("h1", "Резюме"),
        ("p", s.get("summary", "")),
        ("p", f"Вердикт: {VERDICT.get(str(s.get('verdict')), '—')}. {s.get('verdict_reason', '')}"),
        ("h1", "Гипотеза и критерий"),
        ("p", h.get("statement") or e.get("hypothesis") or "—"),
    ]
    if f.get("expected"):
        out.append(("muted", f"Что подтвердит или опровергнет (критерий до расчёта): {f['expected']}"))
    out += [
        ("h1", "Постановка"),
        ("kv", [("Задание методики", e.get("node") or "—"), ("Метод", run.get("template_title") or e.get("method") or "—"),
                ("Параметры", ", ".join(f"{k} = {', '.join(v) if isinstance(v, list) else v}"
                                        for k, v in (run.get("params") or {}).items()) or "—")]),
    ]
    if e.get("setup"):
        out.append(("list", e["setup"]))
    out += [
        ("h1", "Данные"),
        ("kv", [("Датасет", run.get("dataset") or "—"), ("Срез", run.get("snapshot_version") or "—"),
                ("sha256 среза", run.get("dataset_sha256") or "—"), ("Строк", str(run.get("rows") or "—"))]),
        ("h1", "Результаты"),
    ]
    if f.get("kpis"):
        out.append(("kpis", f["kpis"]))
    for c in f.get("charts") or []:
        out.append(("chart", c))
    for title, key in (("Интерпретация", "interpretation"), ("Ограничения", "limitations"), ("Что дальше", "next")):
        if title == "Ограничения" and (s.get("meaning") or s.get("methodology")):
            out.append(("h1", "Что это значит для методики"))
            if s.get("meaning"):
                out.append(("p", s["meaning"]))
            if s.get("methodology"):
                out.append(("p", f"Предложение для методики: {s['methodology']}"))
        items = s.get(key) or []
        if items:
            out += [("h1", title), ("list", items)]
    out += [
        ("h1", "Воспроизводимость"),
        ("kv", [("Коммит runner", run.get("runner_commit") or "—"), ("Окружение", f"python {run.get('python', '?')}, "
                f"requirements.lock {str(run.get('env_lock_sha256', ''))[:16]}…"),
                ("Seed", ", ".join(f"{k} = {v}" for k, v in (run.get("seeds") or {}).items()) or "—"),
                ("Запуск", f"№{run.get('id', '?')}, {run.get('finished_at', '')[:16].replace('T', ' ')}"),
                ("Воспроизводим", "да" if run.get("reproducible") else "нет")]),
    ]
    return out


def docx_bytes(r: dict[str, Any]) -> bytes:
    from docx import Document  # type: ignore[import-untyped]
    from docx.shared import Cm, Pt, RGBColor  # type: ignore[import-untyped]

    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    for kind, data in blocks(r):
        if kind == "title":
            doc.add_heading(data, 0)
        elif kind == "h1":
            doc.add_heading(data, level=1)
        elif kind == "p" and data:
            doc.add_paragraph(str(data))
        elif kind == "muted":
            run = doc.add_paragraph().add_run(str(data))
            run.font.size, run.font.color.rgb = Pt(9), RGBColor(0x5A, 0x6B, 0x62)
        elif kind == "list":
            for item in data:
                doc.add_paragraph(str(item), style="List Bullet")
        elif kind in ("kv", "kpis"):
            rows = data if kind == "kv" else [(k.get("label", ""), f"{k.get('value', '')}  {k.get('note', '')}".strip())
                                              for k in data]
            table = doc.add_table(rows=0, cols=2)
            table.style = "Light Grid Accent 1"
            for a, b in rows:
                cells = table.add_row().cells
                cells[0].text, cells[1].text = str(a), str(b)
        elif kind == "chart":
            doc.add_heading(str(data.get("title", "")), level=2)
            if data.get("subtitle"):
                doc.add_paragraph(str(data["subtitle"])).runs[0].font.size = Pt(9)
            doc.add_picture(io.BytesIO(chart_png(data)), width=Cm(16))
            if data.get("interpretation"):
                doc.add_paragraph(str(data["interpretation"]))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pdf_bytes(r: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    base = ParagraphStyle("base", fontName="DejaVu", fontSize=10, leading=14, textColor=colors.HexColor(TEXT))
    st = {
        "title": ParagraphStyle("t", parent=base, fontName="DejaVu-Bold", fontSize=17, leading=22, spaceAfter=6),
        "h1": ParagraphStyle("h1", parent=base, fontName="DejaVu-Bold", fontSize=13, leading=17, spaceBefore=12, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName="DejaVu-Bold", fontSize=11, leading=15, spaceBefore=8),
        "p": ParagraphStyle("p", parent=base, spaceAfter=4),
        "muted": ParagraphStyle("m", parent=base, fontSize=8.5, leading=12, textColor=colors.HexColor(MUTED)),
    }
    flow: list[Any] = []
    for kind, data in blocks(r):
        if kind in ("title", "h1", "p", "muted") and data:
            flow.append(Paragraph(escape(str(data)), st[kind]))
        elif kind == "list":
            flow.append(ListFlowable([ListItem(Paragraph(escape(str(x)), st["p"])) for x in data], bulletType="bullet",
                                     start="•", leftIndent=12))
        elif kind in ("kv", "kpis"):
            rows = data if kind == "kv" else [(k.get("label", ""), f"{k.get('value', '')}  {k.get('note', '')}".strip())
                                              for k in data]
            t = Table([[Paragraph(escape(str(a)), st["p"]), Paragraph(escape(str(b)), st["p"])] for a, b in rows],
                      colWidths=[5.2 * cm, 11.3 * cm])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            flow += [t, Spacer(1, 6)]
        elif kind == "chart":
            flow.append(Paragraph(escape(str(data.get("title", ""))), st["h2"]))
            if data.get("subtitle"):
                flow.append(Paragraph(escape(str(data["subtitle"])), st["muted"]))
            png = chart_png(data)
            img = Image(io.BytesIO(png))
            ratio = img.imageHeight / img.imageWidth
            img.drawWidth, img.drawHeight = 16 * cm, 16 * cm * ratio
            flow.append(img)
            if data.get("interpretation"):
                flow.append(Paragraph(escape(str(data["interpretation"])), st["p"]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=1.8 * cm, title=f"Отчёт {r['facts'].get('experiment', {}).get('code', '')}").build(flow)
    return buf.getvalue()
