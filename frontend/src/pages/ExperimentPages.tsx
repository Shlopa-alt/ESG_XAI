import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  addReview,
  createExperiment,
  type ExpStatus,
  getExperiment,
  listExperiments,
  OUTCOME_LABEL,
  STATUS_LABEL,
  VERDICT_LABEL,
} from "../api/experiments";
import { useMe } from "../auth/useAuth";
import { experimentRuns, RunsTable } from "./RunPage";
import { Chart } from "../components/Charts";
import { ExperimentEditor, toReport } from "./ExperimentEditor";

/** Пустой раздел: что в нём должно быть и откуда это возьмётся. */
function Empty({ title, text, canEdit }: { title: string; text: string; canEdit: boolean }) {
  return (
    <section className="card empty-state">
      <h2 className="h2">{title}</h2>
      <p className="muted">{text}</p>
      {canEdit && <p className="muted">Заполнить — кнопка «Редактировать» вверху.</p>}
    </section>
  );
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

function NewExperiment({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [direction, setDirection] = useState("");
  const [method, setMethod] = useState("");
  const [data, setData] = useState("");
  const m = useMutation({
    mutationFn: () => createExperiment({ title, hypothesis, direction, method, data_summary: data }),
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      onDone();
      navigate(`/experiments/${e.code}`);
    },
  });
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    m.mutate();
  };
  return (
    <form className="card propose" onSubmit={submit}>
      <h2 className="h2">Новый эксперимент</h2>
      <p className="muted">
        Обычно эксперимент создаётся из принятой гипотезы (раздел «Гипотезы»). Здесь — напрямую, например для
        воспроизведения статьи. Код присвоится автоматически.
      </p>
      <label className="field">
        Название
        <input value={title} onChange={(ev) => setTitle(ev.target.value)} required minLength={3} />
      </label>
      <label className="field">
        Гипотеза — что должно подтвердиться
        <textarea rows={3} value={hypothesis} onChange={(ev) => setHypothesis(ev.target.value)} />
      </label>
      <div className="form-grid">
        <label className="field">
          Направление
          <select value={direction} onChange={(ev) => setDirection(ev.target.value)}>
            <option value="">—</option>
            <option value="Напр. 1">Напр. 1</option>
            <option value="Напр. 2">Напр. 2</option>
            <option value="Методы">Методы</option>
          </select>
        </label>
        <label className="field">
          Метод
          <input value={method} onChange={(ev) => setMethod(ev.target.value)} />
        </label>
        <label className="field span-2">
          Данные
          <input value={data} onChange={(ev) => setData(ev.target.value)} placeholder="DS-05 · ранги RAEX" />
        </label>
      </div>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="review-form">
        <button type="submit" className="btn-primary" disabled={m.isPending}>
          Создать
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Отмена
        </button>
      </div>
    </form>
  );
}

export function Experiments() {
  const q = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const me = useMe();
  const [creating, setCreating] = useState(false);
  const canCreate = me.data?.role === "researcher" || me.data?.role === "owner";
  return (
    <>
      <Head
        eyebrow="ЭКСПЕРИМЕНТЫ"
        title="Реестр экспериментов"
        lead="Воспроизводимые запуски: версия данных, код, окружение, метрики. Отрицательные результаты публикуются наравне с положительными."
      />
      {canCreate && !creating && (
        <div>
          <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
            Новый эксперимент
          </button>
        </div>
      )}
      {creating && <NewExperiment onDone={() => setCreating(false)} />}
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
  const [editing, setEditing] = useState(false);
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
  const canEdit = me.data?.role === "researcher" || me.data?.role === "owner";
  const report = toReport(e.report);
  const charts = report.charts;
  const a = report.analysis;
  const hasAnalysis = Boolean(a.why.length || a.meaning.length || a.next.length);
  return (
    <>
      <div className="muted">
        <Link to="/experiments">Эксперименты</Link> / <span className="mono">{e.code}</span>
      </div>
      <Head eyebrow={`${e.code} · ${e.direction || "направление не указано"}`} title={e.title} lead={e.data_summary} />
      <div className="exp-actions">
        <span>
          <span className={`badge ${BADGE[e.status]}`}>{STATUS_LABEL[e.status]}</span>{" "}
          {e.outcome && <span className="badge st-planned">{OUTCOME_LABEL[e.outcome]}</span>}
        </span>
        {canEdit && !editing && (
          <button type="button" className="btn-primary" onClick={() => setEditing(true)}>
            Редактировать
          </button>
        )}
      </div>
      {editing && <ExperimentEditor e={e} onClose={() => setEditing(false)} />}
      {report.kpis.length > 0 ? (
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
      ) : (
        <Empty title="Ключевые цифры" text="2–4 главных числа результата: что получили, с чем сравнивали, насколько надёжно." canEdit={canEdit} />
      )}
      <section className="card summary-card">
        <h2 className="h2">Вывод</h2>
        <p>{a.summary || e.conclusion || "Вывода пока нет — он появится, когда эксперимент будет посчитан."}</p>
        {a.summary && e.conclusion && <p className="muted" style={{ marginTop: 8 }}>{e.conclusion}</p>}
      </section>
      <div className="grid-2">
        <section className="card">
          <h2 className="h2">Гипотеза</h2>
          <p>{e.hypothesis || "—"}</p>
          {e.method && <p className="muted">Метод: {e.method}</p>}
        </section>
        {e.setup.length > 0 ? (
          <Block title="Постановка" items={e.setup} />
        ) : (
          <Empty title="Постановка" text="Данные, модели, протокол проверки, seed — всё, что нужно, чтобы повторить." canEdit={canEdit} />
        )}
      </div>
      <h2 className="section-title">Результаты</h2>
      {charts.length > 0 ? (
        <div className="charts">
          {charts.map((c) => (
            <Chart key={c.id} spec={c} />
          ))}
        </div>
      ) : e.results.length > 0 ? (
        <Block title="Результат" items={e.results} />
      ) : (
        <Empty
          title="Графиков пока нет"
          text="Они появятся сами, когда зарегистрируется запуск с отчётом, или их можно добавить вручную — вставить таблицу из Excel."
          canEdit={canEdit}
        />
      )}
      <h2 className="section-title">Интерпретация</h2>
      {hasAnalysis ? (
        <div className="grid-3">
          <Block title="Почему так" items={a.why} />
          <Block title="Что это значит для лаборатории" items={a.meaning} />
          <Block title="Что дальше" items={a.next} />
        </div>
      ) : (
        <Empty title="Разбор результата" text="Почему получилось так, что это значит для методологии и что проверить дальше." canEdit={canEdit} />
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
            <dd className="mono">{e.dataset_snapshot || "—"}</dd>
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
                {l.relation}:{" "}
                {l.kind === "article" ? (
                  <Link to={`/knowledge/article/${encodeURIComponent(l.kbrag_id)}`}>{l.title || l.kbrag_id}</Link>
                ) : (
                  l.title || l.kbrag_id
                )}{" "}
                {l.doi && <span className="muted">· DOI {l.doi}</span>}
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
