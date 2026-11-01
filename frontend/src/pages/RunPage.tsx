import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { listExperiments } from "../api/experiments";
import { useMe } from "../auth/useAuth";
import { defaults, type MethodParam, ParamsEditor, type ParamValue } from "../components/ParamsEditor";

export type RunStatus = "queued" | "running" | "done" | "failed" | "stopped";

export interface RunRow {
  id: number;
  experiment: string;
  status: RunStatus;
  resource: string;
  template: string;
  config: { params?: Record<string, unknown>; limit_min?: number };
  runner_commit: string;
  dataset: string;
  dataset_sha256: string;
  env_lock_sha256: string;
  python: string;
  seeds: Record<string, unknown>;
  parts: Record<string, { exit_code: number; seconds: number }>;
  summary: Record<string, unknown>;
  results_path: string;
  mlflow_run_id: string;
  message: string;
  author: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  reproducible: boolean;
  note: string;
}

export interface RunTemplate {
  key: string;
  title: string;
  description: string;
  scope: "generic" | "replication";
  experiment: string;
  dataset: string;
  resource: string;
  limit_min: number;
  params: MethodParam[];
  snapshots: Array<{ id: number; dataset: string; version: string; sha256: string; row_count: number | null }>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

export const listRuns = () => call<RunRow[]>("/runs");
export const experimentRuns = (code: string) => call<RunRow[]>(`/experiments/${code}/runs`);
const getRun = (id: number) => call<RunRow>(`/runs/${id}`);
export const listTemplates = () => call<RunTemplate[]>("/run-templates");
const launch = (body: { template: string; snapshot_id: number; params: Record<string, ParamValue>; experiment?: string }) =>
  call<RunRow>("/runs", { method: "POST", body: JSON.stringify(body) });
const stopRun = (id: number) => call<RunRow>(`/runs/${id}/stop`, { method: "POST" });

const STATUS: Record<RunStatus, string> = {
  queued: "в очереди",
  running: "идёт",
  done: "завершён",
  failed: "сбой",
  stopped: "остановлен",
};
const BADGE: Record<RunStatus, string> = {
  queued: "st-planned",
  running: "st-running",
  done: "st-done",
  failed: "st-failed",
  stopped: "st-review",
};
const ACTIVE = new Set<RunStatus>(["queued", "running"]);
const short = (s: string, n = 10) => (s.length > n ? `${s.slice(0, n)}…` : s);
const when = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—");

function duration(r: RunRow): string {
  const start = r.started_at ? Date.parse(r.started_at) : NaN;
  const end = r.finished_at ? Date.parse(r.finished_at) : Date.now();
  const partsMax = Math.max(0, ...Object.values(r.parts).map((p) => p.seconds));
  const s = Number.isNaN(start) ? partsMax : Math.max(0, (end - start) / 1000);
  return s < 90 ? `${Math.round(s)} с` : `${Math.round(s / 60)} мин`;
}

/** Таблица запусков; на странице эксперимента — только его запуски. */
export function RunsTable({ runs }: { runs: RunRow[] }) {
  if (runs.length === 0) return <p className="muted">Запусков пока нет.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">№</th>
            <th scope="col">Эксперимент</th>
            <th scope="col">Статус</th>
            <th scope="col">Воспроизводим</th>
            <th scope="col">Коммит</th>
            <th scope="col">Срез данных</th>
            <th scope="col">Длительность</th>
            <th scope="col">Кто и когда</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td className="mono">
                <Link to={`/run/${r.id}`}>{r.id}</Link>
              </td>
              <td>
                <Link to={`/experiments/${r.experiment}`} className="mono">
                  {r.experiment}
                </Link>
              </td>
              <td>
                <span className={`badge ${BADGE[r.status]}`}>{STATUS[r.status]}</span>
              </td>
              <td>{r.reproducible ? "да" : <span className="muted">нет: {r.note}</span>}</td>
              <td className="mono" title={r.runner_commit}>
                {short(r.runner_commit, 9) || "—"}
              </td>
              <td className="mono" title={r.dataset_sha256}>
                {r.dataset ? `${r.dataset}@${short(r.dataset_sha256, 8)}` : "—"}
              </td>
              <td className="mono">{duration(r)}</td>
              <td className="muted">
                {r.author || "сервер"}
                <div>{when(r.finished_at ?? r.started_at ?? r.created_at)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LaunchForm({ templates }: { templates: RunTemplate[] }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const [key, setKey] = useState(templates[0]?.key ?? "");
  const t = templates.find((x) => x.key === key);
  const [snapshot, setSnapshot] = useState<number | "">("");
  const [experiment, setExperiment] = useState("");
  const [params, setParams] = useState<Record<string, ParamValue>>({});
  useEffect(() => {
    // новый метод — его срезы и значения по умолчанию
    setSnapshot(t?.snapshots[0]?.id ?? "");
    setParams(defaults(t?.params ?? []));
  }, [t]);
  const m = useMutation({
    mutationFn: launch,
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/run/${run.id}`);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!t || snapshot === "") return;
    m.mutate({ template: t.key, snapshot_id: snapshot, params, ...(t.scope === "generic" ? { experiment } : {}) });
  };
  const generic = t?.scope === "generic";
  return (
    <form className="card launch-form" onSubmit={submit}>
      <h2 className="h2">Новый запуск</h2>
      <label className="field">
        Метод из библиотеки
        <select value={key} onChange={(e) => setKey(e.target.value)}>
          {templates.map((x) => (
            <option key={x.key} value={x.key}>
              {x.scope === "replication" ? "Повтор · " : ""}
              {x.title}
            </option>
          ))}
        </select>
      </label>
      {t && (
        <>
          <p className="muted">
            {t.description}{" "}
            {t.scope === "replication" && (
              <>
                Эксперимент{" "}
                <Link to={`/experiments/${t.experiment}`} className="mono">
                  {t.experiment}
                </Link>
                ,{" "}
              </>
            )}
            ресурс {t.resource === "gpu" ? "видеокарта" : "процессор"}, лимит {t.limit_min} мин.
          </p>
          {generic && (
            <label className="field">
              Эксперимент — в чей реестр запуск
              <select value={experiment} onChange={(e) => setExperiment(e.target.value)} required>
                <option value="">— выберите эксперимент —</option>
                {(exps.data ?? []).map((x) => (
                  <option key={x.code} value={x.code}>
                    {x.code} · {x.title.slice(0, 80)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            Срез данных{t.scope === "replication" ? ` ${t.dataset}` : ""}
            <select value={snapshot} onChange={(e) => setSnapshot(Number(e.target.value))} required>
              {t.snapshots.length === 0 && <option value="">срезов нет — сначала зафиксируйте срез</option>}
              {t.snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.dataset} · {s.version} · sha256 {s.sha256.slice(0, 12)}…{s.row_count ? ` · ${s.row_count} строк` : ""}
                </option>
              ))}
            </select>
          </label>
          <ParamsEditor params={t.params} snapshotId={snapshot === "" ? null : snapshot} value={params} onChange={setParams} idPrefix="launch" />
        </>
      )}
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div>
        <button type="submit" className="btn-primary" disabled={m.isPending || !t || snapshot === "" || (generic && !experiment)}>
          {m.isPending ? "Ставлю в очередь…" : "Запустить"}
        </button>
      </div>
    </form>
  );
}

export function Run() {
  const me = useMe();
  const canLaunch = me.data?.role === "researcher" || me.data?.role === "owner";
  const q = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: (query) => ((query.state.data ?? []).some((r) => ACTIVE.has(r.status)) ? 5_000 : false),
  });
  const templates = useQuery({ queryKey: ["run-templates"], queryFn: listTemplates, enabled: canLaunch });
  const runs = q.data ?? [];
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">ЭКСПЕРИМЕНТЫ · ЗАПУСК</span>
        <h1 className="page-title">Запуски экспериментов</h1>
        <p className="lead">
          Расчёт идёт на сервере лаборатории в зафиксированном окружении. Каждый запуск записывает коммит кода, хеш
          среза данных, окружение и seed. Удачный запуск с чистым коммитом заполняет воспроизводимость эксперимента —
          после этого его можно перевести в «завершён».
        </p>
      </section>
      {canLaunch && templates.data && templates.data.length > 0 && <LaunchForm templates={templates.data} />}
      {templates.isError && (
        <p className="error" role="alert">
          {templates.error.message}
        </p>
      )}
      {q.isError && (
        <p className="error" role="alert">
          {q.error.message}
        </p>
      )}
      <section className="card">
        <h2 className="h2">Реестр запусков</h2>
        <RunsTable runs={runs} />
      </section>
      <section className="card">
        <h2 className="h2">Запуск вручную на сервере</h2>
        <p className="muted">
          Тот же расчёт можно запустить скриптом из <span className="mono">runner/</span>; его итог —{" "}
          <span className="mono">run.json</span> — регистрируется командой в контейнере backend.
        </p>
        <pre className="code">
          {`cd runner/dow30
python run_exp001.py <каталог DS-01> <каталог результатов> --seed 42
docker compose exec backend python -m app.manage import-run EXP-001 /tmp/run.json`}
        </pre>
      </section>
    </>
  );
}

interface StreamEvent {
  seq?: number;
  type: string;
  line?: string;
  status?: RunStatus;
  message?: string;
  done?: number;
  total?: number;
  label?: string;
  name?: string;
  value?: number;
}

/** Живой поток запуска: лог, ход, метрики, статус (SSE /api/runs/{id}/stream). */
function useRunStream(id: number, active: boolean, onFinal: () => void) {
  const [log, setLog] = useState<string[]>([]);
  const [progress, setProgress] = useState<{ done: number; total: number; label: string } | null>(null);
  const [metrics, setMetrics] = useState<Record<string, number>>({});
  const [live, setLive] = useState(false);
  const final = useRef(onFinal);
  final.current = onFinal;
  useEffect(() => {
    setLog([]);
    setProgress(null);
    setMetrics({});
    const seen = new Set<number>();
    const es = new EventSource(`/api/runs/${id}/stream`);
    es.onopen = () => setLive(true);
    es.onmessage = (msg) => {
      const ev = JSON.parse(msg.data as string) as StreamEvent;
      if (ev.seq !== undefined) {
        if (seen.has(ev.seq)) return;
        seen.add(ev.seq);
      }
      if (ev.type === "log" && ev.line !== undefined) {
        const line = ev.line;
        setLog((l) => (l.length > 3000 ? [...l.slice(-2000), line] : [...l, line]));
      } else if (ev.type === "progress" && ev.total) {
        setProgress({ done: ev.done ?? 0, total: ev.total, label: ev.label ?? "" });
      } else if (ev.type === "metric" && ev.name && typeof ev.value === "number") {
        const { name, value } = ev;
        setMetrics((m) => ({ ...m, [name]: value }));
      } else if (ev.type === "status" && ev.status && !ACTIVE.has(ev.status)) {
        es.close();
        setLive(false);
        final.current();
      } else if (ev.type === "status") {
        final.current();
      }
    };
    es.onerror = () => setLive(false);
    return () => es.close();
  }, [id, active]);
  return { log, progress, metrics, live };
}

export function RunDetail() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const qc = useQueryClient();
  const me = useMe();
  const q = useQuery({ queryKey: ["run", id], queryFn: () => getRun(id), enabled: Number.isFinite(id) });
  const r = q.data;
  const active = r ? ACTIVE.has(r.status) : false;
  const stream = useRunStream(id, active, () => void qc.invalidateQueries({ queryKey: ["run", id] }));
  const stop = useMutation({
    mutationFn: () => stopRun(id),
    onSuccess: (run) => qc.setQueryData(["run", id], run),
  });
  const logBox = useRef<HTMLPreElement>(null);
  useEffect(() => {
    const el = logBox.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [stream.log.length]);
  const canStop =
    r !== undefined && active && (me.data?.role === "owner" || (me.data?.login === r.author && me.data?.role !== "reader"));
  const metricRows = useMemo(() => Object.entries(stream.metrics), [stream.metrics]);
  const params = r?.config.params ?? {};
  if (q.isError) {
    return (
      <p className="error" role="alert">
        {q.error.message}
      </p>
    );
  }
  if (!r) return <p className="muted">Загрузка…</p>;
  const pct = stream.progress ? Math.round((100 * stream.progress.done) / stream.progress.total) : null;
  const facts: Array<[string, ReactNode]> = [
    ["Шаблон", r.template || "запуск вручную (run.json)"],
    ...Object.entries(params).map(([k, v]): [string, ReactNode] => [k, Array.isArray(v) ? v.join(", ") : String(v)]),
    ["Срез данных", r.dataset ? `${r.dataset}@${short(r.dataset_sha256, 12)}` : "—"],
    ["Коммит", r.runner_commit || "—"],
    ["Окружение", r.python ? `python ${r.python} · lock ${short(r.env_lock_sha256, 12)}` : "—"],
    ["Воспроизводим", r.reproducible ? "да" : <span className="muted">нет: {r.note}</span>],
    ["Результаты", <span className="run-path">{r.results_path || "—"}</span>],
    ["MLflow", r.mlflow_run_id || "—"],
  ];
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">
          <Link to="/run">ЗАПУСКИ</Link> · №{r.id}
        </span>
        <h1 className="page-title">
          Запуск №{r.id} ·{" "}
          <Link to={`/experiments/${r.experiment}`} className="mono">
            {r.experiment}
          </Link>
        </h1>
        <div className="run-head">
          <span className={`badge ${BADGE[r.status]}`}>{STATUS[r.status]}</span>
          {active && <span className="muted">{stream.live ? "поток подключён" : "подключаюсь к потоку…"}</span>}
          <span className="muted">
            {r.author || "сервер"} · {when(r.created_at)} · {duration(r)}
          </span>
          {canStop && (
            <button type="button" className="btn-ghost" onClick={() => stop.mutate()} disabled={stop.isPending}>
              Остановить
            </button>
          )}
        </div>
        {r.message && <p className={r.status === "failed" ? "error" : "muted"}>{r.message}</p>}
        {stop.isError && (
          <p className="error" role="alert">
            {stop.error.message}
          </p>
        )}
      </section>
      {stream.progress && (
        <section className="card">
          <div className="run-progress-head">
            <strong>
              Ход: {stream.progress.done} из {stream.progress.total}
            </strong>
            <span className="muted">{stream.progress.label}</span>
          </div>
          <div
            className="run-progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct ?? 0}
            aria-label="Ход расчёта"
          >
            <div style={{ width: `${pct ?? 0}%` }} />
          </div>
        </section>
      )}
      <div className="grid-2">
        <section className="card">
          <h2 className="h2">Параметры и воспроизводимость</h2>
          <dl className="run-facts">
            {facts.map(([k, v]) => (
              <div key={k} className="run-fact">
                <dt>{k}</dt>
                <dd className={k === "Воспроизводим" ? undefined : "mono"}>{v}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section className="card">
          <h2 className="h2">Метрики</h2>
          {metricRows.length === 0 && Object.keys(r.summary).length === 0 && (
            <p className="muted">{active ? "Появятся по ходу расчёта." : "Расчёт метрик не передавал."}</p>
          )}
          {metricRows.length > 0 && (
            <table className="table">
              <tbody>
                {metricRows.map(([k, v]) => (
                  <tr key={k}>
                    <th scope="row">{k}</th>
                    <td className="num mono">{v.toLocaleString("ru-RU", { maximumFractionDigits: 4 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {metricRows.length === 0 && Object.keys(r.summary).length > 0 && (
            <pre className="code run-summary">{JSON.stringify(r.summary, null, 2)}</pre>
          )}
        </section>
      </div>
      <section className="card">
        <h2 className="h2">Лог</h2>
        <pre ref={logBox} className="code run-log" aria-live="polite" aria-label="Лог расчёта">
          {stream.log.length > 0 ? stream.log.join("\n") : active ? "Ожидание вывода…" : "Лога нет (запуск вручную или журнал истёк)."}
        </pre>
      </section>
    </>
  );
}
