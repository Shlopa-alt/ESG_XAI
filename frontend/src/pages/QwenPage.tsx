import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useMe } from "../auth/useAuth";

interface QwenStatus {
  worker: boolean;
  model: "off" | "starting" | "on" | "stopping";
  detail: string;
  gpu_used_mb: number | null;
  gpu_total_mb: number | null;
  seen_at: number | null;
  queued: number;
  running: number;
}

interface QwenJob {
  id: number;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  trigger: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  message: string;
  author: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/qwen${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

const MODEL: Record<QwenStatus["model"], string> = {
  off: "выключена — видеокарта свободна",
  starting: "поднимается (1–2 минуты)",
  on: "работает",
  stopping: "выключается",
};
const MODEL_BADGE: Record<QwenStatus["model"], string> = { off: "st-planned", starting: "st-review", on: "st-running", stopping: "st-review" };
export const QWEN_KIND: Record<string, string> = {
  graph: "граф фактов по новым статьям",
  ping: "проверка модели",
  hypotheses: "гипотезы по заданиям методики",
  experiment: "эксперимент для принятой гипотезы",
  report: "текст отчёта об эксперименте",
  cr: "CR по одобренному отчёту",
};
const STATUS: Record<QwenJob["status"], string> = {
  queued: "в очереди",
  running: "выполняется",
  done: "готово",
  failed: "сбой",
  cancelled: "снята",
};
const BADGE: Record<QwenJob["status"], string> = {
  queued: "st-planned",
  running: "st-running",
  done: "st-done",
  failed: "st-failed",
  cancelled: "st-planned",
};
const TRIGGER: Record<string, string> = { manual: "вручную", import: "после импорта", snapshot: "новый срез", run: "после запуска" };
const when = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—");

function took(j: QwenJob): string {
  if (!j.started_at) return "";
  const s = ((j.finished_at ? Date.parse(j.finished_at) : Date.now()) - Date.parse(j.started_at)) / 1000;
  return s < 90 ? `${Math.round(s)} с` : `${Math.round(s / 60)} мин`;
}

export function Qwen() {
  const qc = useQueryClient();
  const me = useMe();
  const canAdd = me.data?.role === "owner";
  const st = useQuery({ queryKey: ["qwen", "status"], queryFn: () => call<QwenStatus>("/status"), refetchInterval: 10_000 });
  const jobs = useQuery({
    queryKey: ["qwen", "jobs"],
    queryFn: () => call<QwenJob[]>("/jobs"),
    refetchInterval: (q) => ((q.state.data ?? []).some((j) => j.status === "queued" || j.status === "running") ? 10_000 : 60_000),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["qwen"] });
  const add = useMutation({
    mutationFn: (kind: string) => call<QwenJob>("/jobs", { method: "POST", body: JSON.stringify({ kind, payload: kind === "graph" ? { kb: "esg" } : {} }) }),
    onSuccess: refresh,
  });
  const cancel = useMutation({ mutationFn: (id: number) => call<QwenJob>(`/jobs/${id}/cancel`, { method: "POST" }), onSuccess: refresh });
  const s = st.data;
  const gpuPct = s?.gpu_used_mb && s.gpu_total_mb ? Math.round((100 * s.gpu_used_mb) / s.gpu_total_mb) : null;
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">БАЗА ЗНАНИЙ · QWEN</span>
        <h1 className="page-title">Задачи Qwen</h1>
        <p className="lead">
          Qwen достраивает граф базы знаний и предлагает гипотезы по заданиям методики, а дальше — эксперименты и отчёты. Модель
          занимает почти всю видеокарту, поэтому работает по требованию: поднимается, когда в очереди есть задача, и
          выключается через 10 минут простоя. Задачи ставятся сами (например, после импорта статьи) или кнопкой.
        </p>
      </section>
      <section className="card qwen-status">
        <div className="run-head">
          <strong>Модель:</strong>
          {s ? <span className={`badge ${MODEL_BADGE[s.model]}`}>{MODEL[s.model]}</span> : <span className="muted">…</span>}
          {s?.detail && <span className="muted">{s.detail}</span>}
          {s && (
            <span className="muted">
              в очереди {s.queued}, выполняется {s.running}
            </span>
          )}
        </div>
        {s && !s.worker && (
          <p className="error" role="alert">
            Обработчик задач не отмечался больше двух минут — задачи копятся, но не выполняются. Его запускает
            deploy\windows\start_all.ps1 (runner\qwen\worker.py).
          </p>
        )}
        {gpuPct !== null && s && (
          <div>
            <div className="run-progress-head">
              <span>Видеокарта</span>
              <span className="muted">
                {((s.gpu_used_mb ?? 0) / 1024).toFixed(1).replace(".", ",")} из {((s.gpu_total_mb ?? 0) / 1024).toFixed(1).replace(".", ",")} ГБ
              </span>
            </div>
            <div className="run-progress" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={gpuPct} aria-label="Занято памяти видеокарты">
              <div style={{ width: `${gpuPct}%` }} />
            </div>
          </div>
        )}
        {canAdd && (
          <div className="review-form">
            <button type="button" className="btn-primary" disabled={add.isPending} onClick={() => add.mutate("graph")}>
              Достроить граф по новым статьям
            </button>
            <button type="button" className="btn-ghost" disabled={add.isPending} onClick={() => add.mutate("hypotheses")}>
              Предложить гипотезы
            </button>
            <button type="button" className="btn-ghost" disabled={add.isPending} onClick={() => add.mutate("ping")}>
              Проверить модель
            </button>
          </div>
        )}
        {(add.error ?? cancel.error) && (
          <p className="error" role="alert">
            {(add.error ?? cancel.error)?.message}
          </p>
        )}
      </section>
      <section className="card">
        <h2 className="h2">Задачи</h2>
        {jobs.isError && <p className="error">{jobs.error.message}</p>}
        {jobs.isSuccess && jobs.data.length === 0 && <p className="muted">Задач ещё не было.</p>}
        {(jobs.data?.length ?? 0) > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">№</th>
                  <th scope="col">Задача</th>
                  <th scope="col">Статус</th>
                  <th scope="col">Итог</th>
                  <th scope="col">Откуда и когда</th>
                </tr>
              </thead>
              <tbody>
                {jobs.data?.map((j) => (
                  <tr key={j.id}>
                    <td className="mono">{j.id}</td>
                    <td>{QWEN_KIND[j.kind] ?? j.kind}</td>
                    <td>
                      <span className={`badge ${BADGE[j.status]}`}>{STATUS[j.status]}</span>
                      {canAdd && j.status === "queued" && (
                        <div>
                          <button type="button" className="link-btn" onClick={() => cancel.mutate(j.id)}>
                            снять
                          </button>
                        </div>
                      )}
                    </td>
                    <td className="import-msg">
                      {j.message || <span className="muted">—</span>}
                      {took(j) && <div className="muted">{took(j)}</div>}
                    </td>
                    <td className="muted">
                      {TRIGGER[j.trigger] ?? j.trigger}
                      {j.author && ` · ${j.author}`}
                      <div>{when(j.created_at)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
