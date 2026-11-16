import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  addReview,
  createExperiment,
  type Experiment as ExperimentRow,
  type ExpStatus,
  type CheckProgress,
  type Outcome,
  getExperiment,
  listExperiments,
  OUTCOME_LABEL,
  STATUS_LABEL,
  VERDICT_LABEL,
} from "../api/experiments";
import { useMe } from "../auth/useAuth";
import { experimentRuns, RunsTable } from "./RunPage";
import { Chart } from "../components/Charts";
import { ReportPanel } from "../components/ReportPanel";
import { ChecksTabs } from "../components/SectionTabs";
import { CycleNext } from "../components/CycleNext";
import { experimentNext, NextStep } from "../components/Ux";
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

// отрицательный итог — нормальный исход, поэтому не «красный», а нейтральный
const OUTCOME_BADGE: Record<Outcome, string> = { confirmed: "st-done", rejected: "st-planned", inconclusive: "st-review" };

type ExpFilter = "all" | "active" | "review" | "confirmed" | "rejected" | "inconclusive";
const EXP_FILTERS: Array<{ key: ExpFilter; label: string; test: (e: ExperimentRow) => boolean }> = [
  { key: "all", label: "Все", test: () => true },
  { key: "active", label: "В работе", test: (e) => ["draft", "planned", "running"].includes(e.status) },
  { key: "review", label: "На проверке", test: (e) => e.status === "review" },
  { key: "confirmed", label: "Идея подтвердилась", test: (e) => e.outcome === "confirmed" },
  { key: "rejected", label: "Идея не подтвердилась", test: (e) => e.outcome === "rejected" },
  { key: "inconclusive", label: "Неоднозначно", test: (e) => e.outcome === "inconclusive" },
];

interface AnalysisChoice {
  title?: string;
  net?: string;
  as_authors?: boolean;
  evidence?: string;
  article?: string;
  primary?: boolean;
  edited?: boolean; // сеть в параметрах сменили вручную — считалась не та, что на карточке
  task?: string;
  hypothesis?: string;
  run_id?: number;
  why?: string[];
}

const TASK_LABEL: Record<string, string> = { predict: "прогноз числового показателя", agreement: "согласованность показателей" };
const NET_LABEL: Record<string, string> = {
  mlp: "перцептрон (MLP)",
  transformer: "трансформер для таблиц",
  gbm: "линейная модель и бустинг",
  linear: "линейная регрессия",
  rank: "ранговая корреляция",
};

function ChoiceBadge({ c }: { c: AnalysisChoice }) {
  if (c.edited) return <span className="badge st-review">сеть заменена вручную</span>;
  if (c.as_authors) return <span className="badge st-done">как у авторов</span>;
  if (c.primary) return <span className="badge st-done">рекомендация платформы</span>;
  return <span className="badge st-planned">альтернатива</span>;
}

/** Почему этот метод и эта сеть: выбор из «Анализа данных» (config.analysis), все расчёты проверки
 * (config.analysis_runs) — например, «как у авторов» и затем замена сети. */
function WhyMethod({ e }: { e: { config?: Record<string, unknown> } }) {
  const c = (e.config?.analysis ?? null) as AnalysisChoice | null;
  if (!c) return null;
  const runs = (Array.isArray(e.config?.analysis_runs) ? e.config.analysis_runs : []) as AnalysisChoice[];
  // цитата статьи уже стоит отдельным блоком — в причинах её не повторяем
  const why = (c.why ?? []).filter((w) => !(c.as_authors && c.evidence && w.includes(c.evidence)));
  return (
    <section className="card">
      <h2 className="h2">Почему этот метод</h2>
      <p>
        {c.title || "—"} <ChoiceBadge c={c} />
      </p>
      {(c.task || c.net) && (
        <p className="muted">
          {c.task && `Тип задачи: ${TASK_LABEL[c.task] ?? c.task}. `}
          {c.net && `Считалась сеть: ${NET_LABEL[c.net] ?? c.net}.`}
        </p>
      )}
      {c.as_authors && c.evidence && (
        <blockquote className="quote">
          «{c.evidence}»{c.article && <cite> — {c.article}</cite>}
        </blockquote>
      )}
      {why.length > 0 && (
        <ul className="list muted">
          {why.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {runs.length > 1 && (
        <>
          <h3 className="h3">Расчёты этой проверки</h3>
          <ol className="list">
            {runs.map((x, i) => (
              <li key={x.run_id ?? i}>
                {x.run_id ? <Link to={`/run/${x.run_id}`}>Расчёт №{x.run_id}</Link> : "Расчёт"}: {NET_LABEL[x.net ?? ""] ?? x.title}{" "}
                <ChoiceBadge c={x} />
              </li>
            ))}
          </ol>
        </>
      )}
      {c.hypothesis && (
        <Link to={`/analysis?h=${encodeURIComponent(c.hypothesis)}`}>Заменить сеть и посчитать ещё раз</Link>
      )}
    </section>
  );
}

const minutes = (m: number) => (m < 1 ? "меньше минуты" : `${Math.round(m)} мин`);

/** Ход проверки (п. 13): сколько расчётов готово, что идёт сейчас и примерно сколько осталось. */
function ProgressLine({ p, detailed = false }: { p?: CheckProgress | null; detailed?: boolean }) {
  if (!p || p.active.length === 0) return null;
  const now = p.active.find((a) => a.status === "running");
  const queued = p.active.filter((a) => a.status === "queued").length;
  return (
    <div className="progress-line muted">
      <span>
        Готово расчётов: {p.done} из {p.total}
        {p.failed ? `, не удалось: ${p.failed}` : ""}.
      </span>{" "}
      {now ? (
        <span>
          Идёт «{now.title}»{now.estimate_min ? ` — ${minutes(now.elapsed_min)} из ~${minutes(now.estimate_min)}` : ""}.
        </span>
      ) : (
        <span>Расчёты ждут исполнителя в очереди.</span>
      )}{" "}
      {queued > 0 && <span>В очереди ещё {queued}. </span>}
      {p.left_min > 0 && <span>Осталось примерно {minutes(p.left_min)}.</span>}
      {detailed && (
        <span>
          {" "}
          {p.active.map((a, i) => (
            <span key={a.run_id}>
              {i > 0 && ", "}
              <Link to={`/run/${a.run_id}`}>расчёт №{a.run_id}</Link>
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

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
      <h2 className="h2">Новая проверка</h2>
      <p className="muted">
        Обычно проверка создаётся из принятой идеи (раздел «Идеи для проверки»). Здесь — напрямую, например для
        воспроизведения статьи. Код присвоится автоматически.
      </p>
      <label className="field">
        Название
        <input value={title} onChange={(ev) => setTitle(ev.target.value)} required minLength={3} />
      </label>
      <label className="field">
        Идея — что должно подтвердиться
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
  const [filter, setFilter] = useState<ExpFilter>("all");
  const [text, setText] = useState("");
  const canCreate = me.data?.role === "researcher" || me.data?.role === "owner";
  const all = Array.isArray(q.data) ? q.data : [];
  const needle = text.trim().toLowerCase();
  const shown = all.filter(
    (e) =>
      (EXP_FILTERS.find((f) => f.key === filter)?.test(e) ?? true) &&
      (!needle || `${e.code} ${e.title} ${e.hypothesis} ${e.data_summary}`.toLowerCase().includes(needle)),
  );
  return (
    <>
      <Head
        eyebrow="ПРОВЕРКИ"
        title="Все проверки"
        lead="Что считали, на каких данных и чем закончилось. Отрицательные результаты публикуются наравне с положительными."
      />
      <ChecksTabs />
      {canCreate && !creating && (
        <div className="exp-actions">
          <button type="button" className="btn-ghost" onClick={() => setCreating(true)}>
            Создать карточку без идеи
          </button>
        </div>
      )}
      {creating && <NewExperiment onDone={() => setCreating(false)} />}
      <div className="toolbar">
        <div className="filters" role="group" aria-label="Итог проверки">
          {EXP_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={filter === f.key ? "chip active" : "chip"}
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
            >
              {f.label} ({all.filter(f.test).length})
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="exp-search">
          Найти проверку
        </label>
        <input
          id="exp-search"
          type="search"
          className="search toolbar-search"
          placeholder="Найти по коду, названию, данным…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
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
              <th scope="col">Проверка</th>
              <th scope="col">Задание методики</th>
              <th scope="col">Статус</th>
              <th scope="col">Данные</th>
              <th scope="col">Итог</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.code}>
                <td>
                  <Link to={`/experiments/${e.code}`} className="mono">
                    {e.code}
                  </Link>
                </td>
                <td>{e.title}</td>
                <td className="mono">{e.methodology_node || e.direction || "—"}</td>
                <td>
                  <span className={`badge ${BADGE[e.status]}`}>{STATUS_LABEL[e.status]}</span>
                  <ProgressLine p={e.progress} />
                </td>
                <td>{e.data_summary}</td>
                <td>
                  {e.outcome ? <span className={`badge ${OUTCOME_BADGE[e.outcome]}`}>{OUTCOME_LABEL[e.outcome]}</span> : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.isPending && <p className="muted">Загрузка…</p>}
        {q.isSuccess && shown.length === 0 && <p className="muted">Ничего не нашлось — смените фильтр или запрос.</p>}
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
        <Link to="/experiments">Проверки</Link> / <span className="mono">{e.code}</span>
      </div>
      <Head
        eyebrow={`${e.code} · ${e.methodology_node ? `методика ${e.methodology_node}` : e.direction || "задание методики не указано"}`}
        title={e.title}
        lead={e.data_summary}
      />
      <div className="exp-actions">
        <span>
          <span className={`badge ${BADGE[e.status]}`}>{STATUS_LABEL[e.status]}</span>{" "}
          {e.outcome && <span className="badge st-planned">{OUTCOME_LABEL[e.outcome]}</span>}
        </span>
        <ProgressLine p={e.progress} detailed />
        {canEdit && !editing && (
          <button type="button" className="btn-primary" onClick={() => setEditing(true)}>
            Редактировать
          </button>
        )}
      </div>
      {!runs.isPending && (
        <NextStep>
          <CycleNext experiment={e.code} fallback={experimentNext(e.status, runs.data ?? [])} />
        </NextStep>
      )}
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
        {a.summary || e.conclusion ? (
          <p>{a.summary || e.conclusion}</p>
        ) : e.draft?.summary ? (
          <>
            <p>
              {e.draft.verdict && <span className={`badge ${OUTCOME_BADGE[e.draft.verdict]}`}>{OUTCOME_LABEL[e.draft.verdict]}</span>}{" "}
              {e.draft.summary}
            </p>
            <p className="muted" style={{ marginTop: 8 }}>
              Предварительный вывод ИИ-помощника по расчёту (отчёт v{e.draft.version}, черновик): его ещё не смотрел
              рецензент. Отчёт целиком и кнопка «На рецензию» — ниже.
            </p>
          </>
        ) : (
          <p>
            {e.progress && e.progress.active.length > 0
              ? "Вывод появится, когда закончатся расчёты, — ход работы виден выше."
              : "Вывода пока нет — он появится, когда проверка будет посчитана."}
          </p>
        )}
        {a.summary && e.conclusion && <p className="muted" style={{ marginTop: 8 }}>{e.conclusion}</p>}
      </section>
      <div className="grid-2">
        <section className="card">
          <h2 className="h2">Идея</h2>
          <p>{e.hypothesis || "—"}</p>
          {e.method && <p className="muted">Метод: {e.method}</p>}
        </section>
        <WhyMethod e={e} />
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
          text="Они появятся сами, когда зарегистрируется расчёт с отчётом, или их можно добавить вручную — вставить таблицу из Excel."
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
        <Empty title="Разбор результата" text="Почему получилось так, что это значит для методики и что проверить дальше." canEdit={canEdit} />
      )}
      {e.report_path && <p className="muted">Полный отчёт в репозитории: <span className="mono">{e.report_path}</span></p>}
      <div className="grid-2">
        <Block title="Ограничения" items={e.limitations} />
        <section className="card">
          <h2 className="h2">Можно ли повторить расчёт</h2>
          <dl className="dl">
            <dt>Коммит runner</dt>
            <dd className="mono">{e.runner_commit || "—"}</dd>
            <dt>Версия данных</dt>
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
      <ReportPanel code={e.code} role={me.data?.role} />
      <section className="card">
        <h2 className="h2">Расчёты</h2>
        <RunsTable runs={Array.isArray(runs.data) ? runs.data : []} />
      </section>
      {e.links.length > 0 && (
        <section className="card">
          <h2 className="h2">Связи с банком статей</h2>
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
