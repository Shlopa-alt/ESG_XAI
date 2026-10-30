import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

export interface RunRow {
  id: number;
  experiment: string;
  status: "queued" | "running" | "done" | "failed" | "stopped";
  runner_commit: string;
  dataset: string;
  dataset_sha256: string;
  env_lock_sha256: string;
  python: string;
  seeds: Record<string, unknown>;
  parts: Record<string, { exit_code: number; seconds: number }>;
  summary: Record<string, unknown>;
  results_path: string;
  started_at: string | null;
  finished_at: string | null;
  reproducible: boolean;
  note: string;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin" });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

export const listRuns = () => get<RunRow[]>("/runs");
export const experimentRuns = (code: string) => get<RunRow[]>(`/experiments/${code}/runs`);

const STATUS = { queued: "в очереди", running: "идёт", done: "завершён", failed: "сбой", stopped: "остановлен" } as const;
const short = (s: string, n = 10) => (s.length > n ? `${s.slice(0, n)}…` : s);
const minutes = (r: RunRow) => Math.round(Math.max(0, ...Object.values(r.parts).map((p) => p.seconds)) / 60);

/** Таблица запусков; experiment — только запуски одного эксперимента. */
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
            <th scope="col">Окружение</th>
            <th scope="col">Части</th>
            <th scope="col">Когда</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td className="mono">{r.id}</td>
              <td>
                <Link to={`/experiments/${r.experiment}`} className="mono">
                  {r.experiment}
                </Link>
              </td>
              <td>
                <span className={`badge ${r.status === "done" ? "st-done" : r.status === "failed" ? "st-review" : "st-running"}`}>
                  {STATUS[r.status]}
                </span>
              </td>
              <td>{r.reproducible ? "да" : <span className="muted">нет: {r.note}</span>}</td>
              <td className="mono" title={r.runner_commit}>
                {short(r.runner_commit, 9)}
              </td>
              <td className="mono" title={r.dataset_sha256}>
                {r.dataset}@{short(r.dataset_sha256, 8)}
              </td>
              <td className="mono" title={r.env_lock_sha256}>
                py {r.python} · {short(r.env_lock_sha256, 8)}
              </td>
              <td>
                {Object.entries(r.parts).map(([name, p]) => (
                  <div key={name} className="mono">
                    {p.exit_code === 0 ? "✓" : "✗"} {name}
                  </div>
                ))}
                <div className="muted">{minutes(r)} мин</div>
              </td>
              <td className="mono">{r.finished_at ? new Date(r.finished_at).toLocaleString("ru-RU") : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Run() {
  const q = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  const runs = Array.isArray(q.data) ? q.data : [];
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">ЭКСПЕРИМЕНТЫ · ЗАПУСК</span>
        <h1 className="page-title">Запуски экспериментов</h1>
        <p className="lead">
          Каждый запуск фиксирует коммит кода, хеш среза данных, окружение и seed. Удачный запуск с чистым коммитом
          заполняет воспроизводимость эксперимента — после этого его можно перевести в «завершён».
        </p>
      </section>
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
        <h2 className="h2">Как запустить расчёт</h2>
        <p className="muted">
          Расчёт запускается на сервере лаборатории скриптом из <span className="mono">runner/</span>. Скрипт сам
          записывает коммит, sha256 среза данных, окружение и seed в <span className="mono">run.json</span>; файл
          регистрируется командой <span className="mono">python -m app.manage import-run</span> в контейнере backend.
        </p>
        <pre className="code">
          {`# EXP-001 · согласованность рейтингов Dow30 (DS-01)
cd runner/dow30
python run_exp001.py <каталог DS-01> <каталог результатов>

# EXP-007 · повтор Hsu et al. (2025) (DS-04)
cd runner/hsu2025
python fetch_mops.py <каталог>/raw              # данные с хешами в manifest.json
python build_dataset.py <каталог>/raw <каталог>/build
python run_exp007.py <каталог> <каталог результатов>

# регистрация: run.json лежит в каталоге результатов
docker compose exec backend python -m app.manage import-run EXP-001 /tmp/run.json`}
        </pre>
      </section>
    </>
  );
}
