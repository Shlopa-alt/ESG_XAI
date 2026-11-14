import { useQuery } from "@tanstack/react-query";

import type { ParamValue } from "./ParamsEditor";

// Цена расчёта до запуска (backend/app/api/runs.py: POST /runs/estimate, app/services/resources.py)

export interface RunEstimate {
  resource: "cpu" | "gpu";
  minutes: number;
  low: number;
  high: number;
  limit_min: number;
  within_limit: boolean;
  basis: string;
  resource_why: string;
  warnings: string[];
  suggestion: { params: Record<string, ParamValue> | null; minutes: number | null; text: string } | null;
  queue: { ahead: number; wait_minutes: number };
  usage: { active: number; active_limit: number; minutes_today: number; minutes_limit: number; unlimited: boolean };
  blocked: string;
}

async function estimate(body: { template: string; snapshot_id: number; params: Record<string, ParamValue> }): Promise<RunEstimate> {
  const res = await fetch("/api/runs/estimate", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => null)) as (RunEstimate & { detail?: unknown }) | null;
  if (!res.ok || data === null) throw new Error(typeof data?.detail === "string" ? data.detail : `Ошибка ${res.status}`);
  return data;
}

const num = (m: number) => m.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
const RESOURCE = { cpu: "на процессоре", gpu: "на видеокарте" } as const;

/** Где посчитается, сколько займёт, лимит, очередь и квота — до кнопки «Запустить». */
export function RunCost({
  template,
  snapshotId,
  params,
  onApply,
}: {
  template: string;
  snapshotId: number | null;
  params: Record<string, ParamValue>;
  onApply?: (params: Record<string, ParamValue>) => void;
}) {
  const q = useQuery({
    queryKey: ["run-estimate", template, snapshotId, JSON.stringify(params)],
    queryFn: () => estimate({ template, snapshot_id: snapshotId as number, params }),
    enabled: Boolean(template) && snapshotId !== null,
    staleTime: 30_000,
  });
  const e = q.data;
  if (!template || snapshotId === null) return null;
  if (q.isError) return <p className="muted">Цену расчёта оценить не удалось: {q.error.message}</p>;
  if (!e || typeof e.minutes !== "number") return <p className="muted">Оцениваю цену расчёта…</p>;
  return (
    <div className={e.blocked ? "run-cost run-cost-blocked" : "run-cost"} role="status" aria-label="Цена расчёта">
      <span className="next-step-label">Цена расчёта</span>
      <p>
        Около <strong>{num(e.minutes)} мин</strong> {RESOURCE[e.resource]} (от {num(e.low)} до {num(e.high)}), лимит метода —{" "}
        {e.limit_min} мин. <span className="muted">Оценка {e.basis}; {e.resource_why}.</span>
      </p>
      <p className="muted">
        {e.queue.ahead > 0
          ? `Впереди в очереди: ${e.queue.ahead} (ждать около ${num(e.queue.wait_minutes)} мин). `
          : "Очередь свободна. "}
        Ваших расчётов идёт: {e.usage.active} из {e.usage.active_limit}
        {e.usage.unlimited
          ? "; дневной квоты у администратора нет."
          : `; за сутки — ${num(e.usage.minutes_today)} из ${e.usage.minutes_limit} мин.`}
      </p>
      {e.warnings.map((w) => (
        <p key={w} className="muted">
          {w}
        </p>
      ))}
      {e.blocked && <p className="error">{e.blocked}</p>}
      {e.suggestion && e.suggestion.params && onApply && (
        <button type="button" className="btn-ghost" onClick={() => e.suggestion?.params && onApply(e.suggestion.params)}>
          {e.suggestion.text} Применить
        </button>
      )}
    </div>
  );
}
