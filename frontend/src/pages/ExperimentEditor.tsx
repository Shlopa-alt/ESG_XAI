import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import type { ExperimentDetail } from "../api/experiments";
import { Chart, type ChartSpec } from "../components/Charts";

export interface Kpi {
  label: string;
  value: string;
  was?: string;
  note?: string;
}

export interface Report {
  kpis: Kpi[];
  charts: ChartSpec[];
  analysis: { summary: string; why: string[]; meaning: string[]; next: string[] };
}

export function toReport(raw: unknown): Report {
  const r = (raw ?? {}) as Partial<Report>;
  const a = (r.analysis ?? {}) as Partial<Report["analysis"]>;
  return {
    kpis: Array.isArray(r.kpis) ? r.kpis : [],
    charts: Array.isArray(r.charts) ? r.charts : [],
    analysis: { summary: a.summary ?? "", why: a.why ?? [], meaning: a.meaning ?? [], next: a.next ?? [] },
  };
}

async function patch(code: string, body: unknown): Promise<ExperimentDetail> {
  const res = await fetch(`/api/experiments/${code}`, {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => null)) as (ExperimentDetail & { detail?: unknown }) | null;
  if (!res.ok || data === null) {
    const d = data?.detail;
    // 422 от pydantic — список ошибок; показываем первую по-человечески
    if (Array.isArray(d) && d[0]) throw new Error(String((d[0] as { msg?: string }).msg ?? "Ошибка данных"));
    throw new Error(typeof d === "string" ? d : `Ошибка ${res.status}`);
  }
  return data;
}

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const num = (s: string) => Number(s.replace(/\s/g, "").replace(",", ".").replace("−", "-"));

/** Таблица из Excel/текста → данные графика. Разделитель — табуляция или «;». */
type ParsedChart =
  | { categories: string[]; series: Array<{ name: string; values: number[] }> }
  | { rows: Array<{ name: string; mean: number; min: number; max: number }> };

export function parseChart(kind: "bars" | "ranges", text: string): ParsedChart {
  const rows = lines(text).map((l) => l.split(/\t|;/).map((c) => c.trim()));
  if (rows.length < 2) throw new Error("Нужна строка заголовков и хотя бы одна строка данных");
  const [head, ...body] = rows as [string[], ...string[][]];
  if (kind === "ranges") {
    return {
      rows: body.map((r) => {
        const [name = "", mean = "", min = "", max = ""] = r;
        const v = { name, mean: num(mean), min: num(min), max: num(max) };
        if ([v.mean, v.min, v.max].some(Number.isNaN)) throw new Error(`Не число в строке «${name}»`);
        return v;
      }),
    };
  }
  const names = head.slice(1);
  if (names.length === 0 || names.length > 3) throw new Error("Серий должно быть от 1 до 3 — столбцы после первого");
  return {
    categories: body.map((r) => r[0] ?? ""),
    series: names.map((n, i) => ({
      name: n,
      values: body.map((r) => {
        const v = num(r[i + 1] ?? "");
        if (Number.isNaN(v)) throw new Error(`Не число: «${r[0]}», «${n}»`);
        return v;
      }),
    })),
  };
}

function chartToText(c: ChartSpec): string {
  const f = (v: number) => String(v).replace(".", ",");
  if (c.kind === "ranges") return ["Название;Среднее;Мин;Макс", ...c.rows.map((r) => [r.name, f(r.mean), f(r.min), f(r.max)].join(";"))].join("\n");
  return [["Категория", ...c.series.map((s) => s.name)].join(";"), ...c.categories.map((cat, i) => [cat, ...c.series.map((s) => f(s.values[i] ?? 0))].join(";"))].join("\n");
}

function ChartForm({ initial, onSave, onCancel }: { initial?: ChartSpec; onSave: (c: ChartSpec) => void; onCancel: () => void }) {
  const [kind, setKind] = useState<"bars" | "ranges">(initial?.kind ?? "bars");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [subtitle, setSubtitle] = useState(initial?.subtitle ?? "");
  const [unit, setUnit] = useState(initial?.unit ?? "");
  const [refValue, setRefValue] = useState(initial?.reference ? String(initial.reference.value) : "");
  const [refLabel, setRefLabel] = useState(initial?.reference?.label ?? "");
  const [interp, setInterp] = useState(initial?.interpretation ?? "");
  const [data, setData] = useState(initial ? chartToText(initial) : "");
  let preview: ChartSpec | null = null;
  let problem = "";
  try {
    if (data.trim() && title.trim()) {
      const parsed = parseChart(kind, data);
      const reference = refValue.trim() ? { value: num(refValue), label: refLabel } : undefined;
      preview = { id: initial?.id ?? `c${Date.now()}`, kind, title, subtitle, unit, reference, interpretation: interp, ...parsed } as ChartSpec;
    }
  } catch (e) {
    problem = (e as Error).message;
  }
  const placeholder =
    kind === "bars"
      ? "Категория;Статья;Повтор\nMLR;-0,28;-0,11\nLSTM;0,71;0,03"
      : "Название;Среднее;Мин;Макс\nLightGBM;-0,12;-0,79;0,18";
  return (
    <div className="card chart-form">
      <div className="form-grid">
        <label className="field">
          Тип
          <select value={kind} onChange={(e) => setKind(e.target.value as "bars" | "ranges")}>
            <option value="bars">Полосы: сравнение величин (до 3 серий)</option>
            <option value="ranges">Диапазоны: среднее и разброс</option>
          </select>
        </label>
        <label className="field">
          Единица
          <input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="R², %, ρ" />
        </label>
        <label className="field span-2">
          Заголовок
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Что показывает график" />
        </label>
        <label className="field span-2">
          Подзаголовок
          <input value={subtitle} onChange={(e) => setSubtitle(e.target.value)} placeholder="Как читать: чем правее, тем лучше…" />
        </label>
        <label className="field">
          Опорная линия
          <input value={refValue} onChange={(e) => setRefValue(e.target.value)} placeholder="0" />
        </label>
        <label className="field">
          Подпись линии
          <input value={refLabel} onChange={(e) => setRefLabel(e.target.value)} placeholder="прогноз средним" />
        </label>
        <label className="field span-2">
          Данные — вставьте таблицу из Excel или строки через «;»
          <textarea rows={6} value={data} onChange={(e) => setData(e.target.value)} placeholder={placeholder} className="mono" />
        </label>
        <label className="field span-2">
          Интерпретация — что видно на графике и почему это важно
          <textarea rows={3} value={interp} onChange={(e) => setInterp(e.target.value)} />
        </label>
      </div>
      {problem && <p className="error">{problem}</p>}
      {preview && (
        <div className="chart-preview">
          <span className="eyebrow">ПРЕДПРОСМОТР</span>
          <Chart spec={preview} />
        </div>
      )}
      <div className="review-form">
        <button type="button" className="btn-primary" disabled={!preview} onClick={() => preview && onSave(preview)}>
          Сохранить график
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </div>
  );
}

type Tab = "about" | "result" | "report" | "charts";

export function ExperimentEditor({ e, onClose }: { e: ExperimentDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const base = toReport(e.report);
  const [tab, setTab] = useState<Tab>("about");
  const [title, setTitle] = useState(e.title);
  const [hypothesis, setHypothesis] = useState(e.hypothesis);
  const [method, setMethod] = useState(e.method);
  const [dataSummary, setDataSummary] = useState(e.data_summary);
  const [setup, setSetup] = useState(e.setup.join("\n"));
  const [status, setStatus] = useState(e.status);
  const [outcome, setOutcome] = useState(e.outcome ?? "");
  const [conclusion, setConclusion] = useState(e.conclusion);
  const [limitations, setLimitations] = useState(e.limitations.join("\n"));
  const [kpis, setKpis] = useState<Kpi[]>(base.kpis);
  const [summary, setSummary] = useState(base.analysis.summary);
  const [why, setWhy] = useState(base.analysis.why.join("\n"));
  const [meaning, setMeaning] = useState(base.analysis.meaning.join("\n"));
  const [next, setNext] = useState(base.analysis.next.join("\n"));
  const [charts, setCharts] = useState<ChartSpec[]>(base.charts);
  const [editing, setEditing] = useState<number | "new" | null>(null);

  const save = useMutation({
    mutationFn: () =>
      patch(e.code, {
        title,
        hypothesis,
        method,
        data_summary: dataSummary,
        setup: lines(setup),
        conclusion,
        limitations: lines(limitations),
        ...(outcome ? { outcome } : {}),
        ...(status !== e.status ? { status } : {}),
        report: {
          kpis: kpis.filter((k) => k.label.trim() && k.value.trim()),
          charts,
          analysis: { summary, why: lines(why), meaning: lines(meaning), next: lines(next) },
        },
      }),
    onSuccess: (data) => {
      qc.setQueryData(["experiment", e.code], data);
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      onClose();
    },
  });
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    save.mutate();
  };
  const setKpi = (i: number, k: Partial<Kpi>) => setKpis(kpis.map((x, j) => (j === i ? { ...x, ...k } : x)));
  const TABS: Array<[Tab, string]> = [
    ["about", "Описание"],
    ["result", "Результат"],
    ["report", "Цифры и разбор"],
    ["charts", `Графики (${charts.length})`],
  ];

  return (
    <form className="card editor" onSubmit={submit}>
      <div className="editor-head">
        <h2 className="h2">Редактирование {e.code}</h2>
        <div className="filters" role="tablist" aria-label="Разделы эксперимента">
          {TABS.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "chip active" : "chip"} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "about" && (
        <div className="form-grid">
          <label className="field span-2">
            Название
            <input value={title} onChange={(ev) => setTitle(ev.target.value)} required minLength={3} />
          </label>
          <label className="field span-2">
            Гипотеза — что должно подтвердиться
            <textarea rows={3} value={hypothesis} onChange={(ev) => setHypothesis(ev.target.value)} />
          </label>
          <label className="field">
            Метод
            <input value={method} onChange={(ev) => setMethod(ev.target.value)} placeholder="Модели, протокол проверки" />
          </label>
          <label className="field">
            Данные
            <input value={dataSummary} onChange={(ev) => setDataSummary(ev.target.value)} placeholder="DS-04 · 194 компании" />
          </label>
          <label className="field span-2">
            Постановка — по пункту в строке
            <textarea rows={5} value={setup} onChange={(ev) => setSetup(ev.target.value)} />
          </label>
        </div>
      )}

      {tab === "result" && (
        <div className="form-grid">
          <label className="field">
            Статус
            <select value={status} onChange={(ev) => setStatus(ev.target.value as typeof status)}>
              <option value="draft">черновик</option>
              <option value="planned">запланирован</option>
              <option value="running">в работе</option>
              <option value="review">на проверке</option>
              <option value="done">завершён — нужна воспроизводимость</option>
              <option value="failed">сбой</option>
            </select>
          </label>
          <label className="field">
            Итог
            <select value={outcome} onChange={(ev) => setOutcome(ev.target.value)}>
              <option value="">ещё нет</option>
              <option value="confirmed">гипотеза подтверждена</option>
              <option value="rejected">гипотеза отклонена</option>
              <option value="inconclusive">результат неоднозначен</option>
            </select>
          </label>
          <label className="field span-2">
            Вывод — одной-двумя фразами
            <textarea rows={3} value={conclusion} onChange={(ev) => setConclusion(ev.target.value)} />
          </label>
          <label className="field span-2">
            Ограничения — по пункту в строке
            <textarea rows={4} value={limitations} onChange={(ev) => setLimitations(ev.target.value)} />
          </label>
          <p className="muted span-2">
            «Завершён» сохранится, только если у эксперимента есть коммит кода, срез данных, окружение и seed — их
            заполняет зарегистрированный запуск.
          </p>
        </div>
      )}

      {tab === "report" && (
        <div className="form-grid">
          <fieldset className="span-2 kpi-editor">
            <legend>Ключевые цифры — до 8, видны первыми на странице</legend>
            {kpis.map((k, i) => (
              <div key={i} className="kpi-row">
                <input aria-label="Что это" placeholder="Что это: R² LSTM по ROA" value={k.label} onChange={(ev) => setKpi(i, { label: ev.target.value })} />
                <input aria-label="Значение" placeholder="0,03" value={k.value} onChange={(ev) => setKpi(i, { value: ev.target.value })} />
                <input aria-label="Было" placeholder="было: 0,71 в статье" value={k.was ?? ""} onChange={(ev) => setKpi(i, { was: ev.target.value })} />
                <input aria-label="Пояснение" placeholder="пояснение" value={k.note ?? ""} onChange={(ev) => setKpi(i, { note: ev.target.value })} />
                <button type="button" className="link-btn" onClick={() => setKpis(kpis.filter((_, j) => j !== i))}>
                  убрать
                </button>
              </div>
            ))}
            {kpis.length < 8 && (
              <button type="button" className="btn-ghost" onClick={() => setKpis([...kpis, { label: "", value: "" }])}>
                Добавить цифру
              </button>
            )}
          </fieldset>
          <label className="field span-2">
            Вывод коротко — главная мысль для того, кто прочтёт только его
            <textarea rows={3} value={summary} onChange={(ev) => setSummary(ev.target.value)} />
          </label>
          <label className="field">
            Почему так — по пункту в строке
            <textarea rows={5} value={why} onChange={(ev) => setWhy(ev.target.value)} />
          </label>
          <label className="field">
            Что это значит для лаборатории
            <textarea rows={5} value={meaning} onChange={(ev) => setMeaning(ev.target.value)} />
          </label>
          <label className="field span-2">
            Что дальше
            <textarea rows={3} value={next} onChange={(ev) => setNext(ev.target.value)} />
          </label>
        </div>
      )}

      {tab === "charts" && (
        <div className="charts-editor">
          {charts.map((c, i) =>
            editing === i ? (
              <ChartForm
                key={c.id}
                initial={c}
                onSave={(nc) => {
                  setCharts(charts.map((x, j) => (j === i ? nc : x)));
                  setEditing(null);
                }}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <div key={c.id} className="chart-item">
                <span>
                  <strong>{c.title}</strong> <span className="muted">· {c.kind === "bars" ? "полосы" : "диапазоны"}</span>
                </span>
                <span className="actions">
                  <button type="button" className="link-btn" onClick={() => setEditing(i)}>
                    изменить
                  </button>
                  <button type="button" className="link-btn" onClick={() => setCharts(charts.filter((_, j) => j !== i))}>
                    удалить
                  </button>
                </span>
              </div>
            ),
          )}
          {editing === "new" ? (
            <ChartForm
              onSave={(nc) => {
                setCharts([...charts, nc]);
                setEditing(null);
              }}
              onCancel={() => setEditing(null)}
            />
          ) : (
            <button type="button" className="btn-ghost" onClick={() => setEditing("new")}>
              Добавить график
            </button>
          )}
          <p className="muted">Графики, посчитанные самим расчётом, добавляются сюда автоматически при регистрации запуска.</p>
        </div>
      )}

      {save.isError && (
        <p className="error" role="alert">
          {save.error.message}
        </p>
      )}
      <div className="review-form editor-actions">
        <button type="submit" className="btn-primary" disabled={save.isPending || editing !== null}>
          Сохранить
        </button>
        <button type="button" className="btn-ghost" onClick={onClose}>
          Отмена
        </button>
      </div>
    </form>
  );
}
