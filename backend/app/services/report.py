"""Отчёт эксперимента: ключевые цифры, графики, разбор. Схема проверяется при записи,
чтобы страница эксперимента всегда могла его нарисовать."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class Kpi(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=40)
    was: str = ""
    note: str = ""


class Reference(BaseModel):
    value: float
    label: str = ""


class BarSeries(BaseModel):
    name: str = Field(min_length=1)
    values: list[float]


class BarChart(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    kind: Literal["bars"] = "bars"
    title: str = Field(min_length=1)
    subtitle: str = ""
    unit: str = ""
    reference: Reference | None = None
    categories: list[str] = Field(min_length=1, max_length=40)
    series: list[BarSeries] = Field(min_length=1, max_length=3)  # больше трёх — не различить
    interpretation: str = ""

    @model_validator(mode="after")
    def same_length(self) -> "BarChart":
        for s in self.series:
            if len(s.values) != len(self.categories):
                raise ValueError(f"в серии «{s.name}» {len(s.values)} значений, а категорий "
                                 f"{len(self.categories)}")
        return self


class RangeRow(BaseModel):
    name: str = Field(min_length=1)
    mean: float
    min: float
    max: float

    @model_validator(mode="after")
    def ordered(self) -> "RangeRow":
        if not self.min <= self.mean <= self.max:
            raise ValueError(f"«{self.name}»: нужно min ≤ среднее ≤ max")
        return self


class RangeChart(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    kind: Literal["ranges"] = "ranges"
    title: str = Field(min_length=1)
    subtitle: str = ""
    unit: str = ""
    reference: Reference | None = None
    rows: list[RangeRow] = Field(min_length=1, max_length=40)
    interpretation: str = ""


Chart = Annotated[BarChart | RangeChart, Field(discriminator="kind")]


class Analysis(BaseModel):
    summary: str = ""
    why: list[str] = []
    meaning: list[str] = []
    next: list[str] = []


class Report(BaseModel):
    kpis: list[Kpi] = Field(default=[], max_length=8)
    charts: list[Chart] = Field(default=[], max_length=12)
    analysis: Analysis = Analysis()


def merge_run_report(current: dict[str, Any], incoming: Report) -> dict[str, Any]:
    """Отчёт из запуска дополняет отчёт эксперимента: графики заменяются по id, ключевые
    цифры — если пришли; разбор, написанный людьми, не трогается, если он уже есть."""
    base = Report.model_validate(current or {})
    charts = {c.id: c for c in base.charts}
    for c in incoming.charts:
        charts[c.id] = c
    analysis = base.analysis
    if not (analysis.summary or analysis.why or analysis.meaning or analysis.next):
        analysis = incoming.analysis
    merged = Report(kpis=incoming.kpis or base.kpis, charts=list(charts.values()), analysis=analysis)
    return merged.model_dump()
