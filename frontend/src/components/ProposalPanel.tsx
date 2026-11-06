import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

export interface Proposal {
  id: number;
  hypothesis: string;
  status: "proposed" | "approved" | "rejected";
  from_qwen: boolean; // false — проверку настроил человек
  title: string;
  method: string;
  method_title: string;
  snapshot_id: number | null;
  snapshot: string;
  params: Record<string, unknown>;
  setup: string[];
  expected: string;
  rationale: string;
  problems: string;
  note: string;
  decided_by: string;
  experiment: string;
  run_id: number | null;
  created_at: string;
}

/** Что с предложением, которого ещё нет: последняя задача Qwen и на связи ли обработчик. */
export interface ProposalWait {
  job: "none" | "queued" | "running" | "done" | "failed" | "cancelled";
  worker: boolean;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/experiment-proposals${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

const post = <T,>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const proposalsFor = (code: string) => call<Proposal[]>(`?hypothesis=${encodeURIComponent(code)}`);
export const proposalWait = (code: string) => call<ProposalWait>(`/wait?hypothesis=${encodeURIComponent(code)}`);
export const requestProposal = (code: string) => post<ProposalWait>("/request", { hypothesis: code });
export const approveProposal = (id: number, body: Record<string, unknown>) => post<Proposal>(`/${id}/approve`, body);
export const rejectProposal = (id: number, note: string) => post<Proposal>(`/${id}/reject`, { note });
export const manualProposal = (body: Record<string, unknown>) => post<Proposal>("/manual", body);

/** История предложений на карточке гипотезы; решать по предложению — в мастере на странице запуска. */
export function ProposalPanel({ code, status }: { code: string; status: string }) {
  const q = useQuery({
    queryKey: ["proposals", code],
    queryFn: () => proposalsFor(code),
    enabled: status === "testing" || status === "tested",
  });
  const list = q.data ?? [];
  const approved = list.find((p) => p.status === "approved");
  return (
    <>
      {approved && (
        <p className="muted">
          {approved.from_qwen ? "Эксперимент по предложению Qwen" : "Эксперимент настроен вручную"}:{" "}
          <Link to={`/experiments/${approved.experiment}`} className="mono">
            {approved.experiment}
          </Link>
          {approved.run_id && (
            <>
              , запуск <Link to={`/run/${approved.run_id}`}>№{approved.run_id}</Link>
            </>
          )}{" "}
          ({approved.from_qwen ? "одобрил" : "настроил"} {approved.decided_by})
        </p>
      )}
      {approved?.expected && <p className="muted">Что подтвердит или опровергнет: {approved.expected}</p>}
      {list
        .filter((p) => p.status === "rejected")
        .map((p) => (
          <p key={p.id} className="muted">
            Предложение Qwen «{p.title}» отклонено ({p.decided_by}): {p.note}
          </p>
        ))}
    </>
  );
}
