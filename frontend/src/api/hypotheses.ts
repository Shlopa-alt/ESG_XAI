export type HStatus = "proposed" | "accepted" | "rejected" | "testing" | "tested";

export interface KbRefIn {
  kind: "article" | "fact" | "entity";
  kbrag_id: string;
  kb_path?: string;
  title?: string;
  doi?: string;
  quote?: string;
  page?: number | null;
}

export interface Hypothesis {
  code: string;
  title: string;
  statement: string;
  rationale: string;
  direction: string;
  status: HStatus;
  decision_note: string;
  author: string;
  decided_by: string;
  experiment: string;
  methodology_node: string;
  created_at: string;
  refs: Array<{ kind: string; kbrag_id: string; title: string; doi: string; quote: string }>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) {
    const d = body?.detail;
    throw new Error(typeof d === "string" ? d : `Ошибка ${res.status}`);
  }
  return body;
}

export const listHypotheses = () => call<Hypothesis[]>("/hypotheses");
export const proposeHypothesis = (h: {
  title: string;
  statement: string;
  rationale: string;
  direction: string;
  methodology_node?: string;
  refs: KbRefIn[];
}) => call<Hypothesis>("/hypotheses", { method: "POST", body: JSON.stringify(h) });
export const decideHypothesis = (code: string, status: "accepted" | "rejected", note: string) =>
  call<Hypothesis>(`/hypotheses/${code}`, { method: "PATCH", body: JSON.stringify({ status, note }) });
export const experimentFromHypothesis = (code: string) =>
  call<Hypothesis>(`/hypotheses/${code}/experiment`, { method: "POST" });

export const H_STATUS_LABEL: Record<HStatus, string> = {
  proposed: "предложена",
  accepted: "принята к проверке",
  rejected: "отклонена",
  testing: "проверяется",
  tested: "проверена",
};

export const H_BADGE: Record<HStatus, string> = {
  proposed: "st-planned",
  accepted: "st-running",
  rejected: "st-planned",
  testing: "st-review",
  tested: "st-done",
};
