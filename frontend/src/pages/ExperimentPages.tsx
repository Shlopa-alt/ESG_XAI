import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  addReview,
  type ExpStatus,
  getExperiment,
  listExperiments,
  OUTCOME_LABEL,
  STATUS_LABEL,
  VERDICT_LABEL,
} from "../api/experiments";
import { useMe } from "../auth/useAuth";
import { experimentRuns, RunsTable } from "./RunPage";
import { Chart, type ChartSpec } from "../components/Charts";

interface ExperimentReport {
  kpis?: Array<{ label: string; value: string; was?: string; note?: string }>;
  charts?: ChartSpec[];
  analysis?: { summary?: string; why?: string[]; meaning?: string[]; next?: string[] };
}

const BADGE: Record<ExpStatus, string> = {
  draft: "st-planned",
  planned: "st-planned",
  running: "st-running",
  review: "st-review",
  done: "st-done",
  failed: "st-review",
};

function Head({ eyebrow, title, lead }: { eyebrow: string; title: string; lead: string }) {
  return (
    <section className="page-head">
      <span className="eyebrow">{eyebrow}</span>
      <h1 className="page-title">{title}</h1>
      <p className="lead">{lead}</p>
    </section>
  );
}

export function Experiments() {
  const q = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  return (
    <>
      <Head
        eyebrow="ЭКСПЕРИМЕНТЫ"
        title="Реестр экспериментов"
        lead="Воспроизводимые запуски: версия данных, код, окружение, метрики. Отрицательные результаты публикуются наравне с положительными."
      />
      {q.isError && (
        <p className="error" role="alert">
          {q.error.message}
        </p>
      )}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Код</th>
              <th scope="col">Эксперимент</th>
              <th scope="col">Направление</th>
              <th scope="col">Статус</th>
              <th scope="col">Данные</th>
              <th scope="col">Итог</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((e) => (
              <tr key={e.code}>
                <td>
                  <Link to={`/experiments/${e.code}`} className="mono">
                    {e.code}
                  </Link>
                </td>
                <td>{e.title}</td>
                <td>{e.direction}</td>
                <td>
                  <span className={`badge ${BADGE[e.status]}`}>{STATUS_LABEL[e.status]}</span>
                </td>
                <td>{e.data_summary}</td>
                <td>{e.outcome ? OUTCOME_LABEL[e.outcome] : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.isPending && <p className="muted">Загрузка…</p>}
      </div>
    </>
  );
}

function Block({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section className="card">
      <h2 className="h2">{title}</h2>
      <ul className="list">
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </section>
  );
}

function ReviewForm({ code }: { code: string }) {
  const qc = useQueryClient();
  const [verdict, setVerdict] = useState("approve");
  const [text, setText] = useState("");
  const m = useMutation({
    mutationFn: () => addReview(code, verdict, text),
    onSuccess: (data) => {
      qc.setQueryData(["experiment", code], data);
      setText("");
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <form className="review-form" onSubmit={submit}>
      <label className="field inline">
        Вердикт
        <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
          {Object.entries(VERDICT_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="field inline grow">
        Комментарий
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} />
      </label>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <button type="submit" className="btn-primary" disabled={m.isPending}>
        Добавить рецензию
      </button>
    </form>
  );
}

export function Experiment() {
  const { code = "" } = useParams();
  const me = useMe();
  const q = useQuery({ queryKey: ["experiment", code], queryFn: () => getExperiment(code) });
  const runs = useQuery({ queryKey: ["runs", code], queryFn: () => experimentRuns(code) });
  if (q.isPending) return <p className="muted">Загрузка…</p>;
  if (q.isError) {
    return (
      <p className="error" role="alert">
        {q.error.message}
      </p>
    );
  }
  const e = q.data;
  const canReview = me.data?.role === "reviewer" || me.data?.role === "owner";
  const report = (e.report ?? {}) as ExperimentReport;
  const charts = Array.isArray(report.charts) ? report.charts : [];
  return (
    <>
      <div className="muted">
        <Link to="/experiments">Эксперименты</Link> / <span className="mono">{e.code}</span>
      </div>
      <Head eyebrow={`${e.code} · ${e.direction}`} title={e.title} lead={e.data_summary} />
      <div>
        <span className={`badge ${BADGE[e.status]}`}>{STATUS_LABEL[e.status]}</span>{" "}
        {e.outcome && <span className="badge st-planned">{OUTCOME_LABEL[e.outcome]}</span>}
      </div>
      {report.kpis && report.kpis.length > 0 && (
        <div className="kpis">
          {report.kpis.map((k) => (
            <div key={k.label} className="card kpi">
              <span className="kpi-label">{k.label}</span>
              <span className="kpi-value">{k.value}</span>
              {k.was && <span className="kpi-was">{k.was}</span>}
              {k.note && <span className="muted">{k.note}</span>}
            </div>
          ))}
        </div>
      )}
      <section className="card summary-card">
        <h2 className="h2">Вывод</h2>
        <p>{report.analysis?.summary || e.conclusion || "—"}</p>
        {report.analysis?.summary && e.conclusion && <p className="muted" style={{ marginTop: 8 }}>{e.conclusion}</p>}
      </section>
      <div className="grid-2">
        <section className="card">
          <h2 className="h2">Гипотеза</h2>
          <p>{e.hypothesis}</p>
          {e.method && <p className="muted">Метод: {e.method}</p>}
        </section>
        <Block title="Постановка" items={e.setup} />
      </div>
      {charts.length > 0 && (
        <>
          <h2 className="section-title">Результаты</h2>
          <div className="charts">
            {charts.map((c) => (
              <Chart key={c.id} spec={c} />
            ))}
          </div>
        </>
      )}
      {charts.length === 0 && <Block title="Результат" items={e.results} />}
      {report.analysis && (
        <>
          <h2 className="section-title">Интерпретация</h2>
          <div className="grid-3">
            <Block title="Почему так" items={report.analysis.why ?? []} />
            <Block title="Что это значит для лаборатории" items={report.analysis.meaning ?? []} />
            <Block title="Что дальше" items={report.analysis.next ?? []} />
          </div>
        </>
      )}
      {e.report_path && <p className="muted">Полный отчёт в репозитории: <span className="mono">{e.report_path}</span></p>}
      <div className="grid-2">
        <Block title="Ограничения" items={e.limitations} />
        <section className="card">
          <h2 className="h2">Воспроизводимость</h2>
          <dl className="dl">
            <dt>Коммит runner</dt>
            <dd className="mono">{e.runner_commit || "—"}</dd>
            <dt>Срез данных</dt>
            <dd className="mono">{e.dataset_snapshot_id ?? "—"}</dd>
            <dt>Seed</dt>
            <dd className="mono">{e.seed ?? "—"}</dd>
            <dt>Окружение</dt>
            <dd className="mono">{e.env_lock ? "зафиксировано" : "—"}</dd>
          </dl>
          <ul className="list">
            {e.reproducibility.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </section>
      </div>
      <section className="card">
        <h2 className="h2">Запуски</h2>
        <RunsTable runs={Array.isArray(runs.data) ? runs.data : []} />
      </section>
      {e.links.length > 0 && (
        <section className="card">
          <h2 className="h2">Связи с базой знаний</h2>
          <ul className="list">
            {e.links.map((l) => (
              <li key={`${l.relation}-${l.kbrag_id}`}>
                {l.relation}: {l.title || l.kbrag_id} {l.doi && <span className="muted">· DOI {l.doi}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="card">
        <h2 className="h2">Рецензии</h2>
        {e.reviews.length === 0 && <p className="muted">Рецензий пока нет.</p>}
        <ul className="list">
          {e.reviews.map((r) => (
            <li key={r.id}>
              <strong>{r.reviewer}</strong> — {VERDICT_LABEL[r.verdict]}
              {r.text && <p className="muted">{r.text}</p>}
            </li>
          ))}
        </ul>
        {canReview && <ReviewForm code={e.code} />}
      </section>
    </>
  );
}
