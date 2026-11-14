/** Тип связи: как фактор влияет и на какие показатели (design/GLOSSARY.md). */
export type Effect = "increases" | "decreases" | "no_effect" | "mixed";
export type TargetKind = "financial" | "nonfinancial";

export const EFFECT_LABEL: Record<Effect, string> = {
  increases: "повышает",
  decreases: "снижает",
  no_effect: "не влияет",
  mixed: "влияет по-разному",
};

export const TARGET_KIND_LABEL: Record<TargetKind, string> = {
  financial: "финансовые результаты",
  nonfinancial: "нефинансовые результаты",
};

/** «повышает · финансовые результаты»; пусто — тип связи не указан. */
export function linkType(effect: Effect | "", target: TargetKind | ""): string {
  return [effect ? EFFECT_LABEL[effect] : "", target ? TARGET_KIND_LABEL[target] : ""].filter(Boolean).join(" · ");
}

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
  methodology_node_title: string;
  effect: Effect | "";
  target_kind: TargetKind | "";
  source: "human" | "qwen";
  suggested: { dataset?: string; method?: string; data_needed?: string };
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
  effect?: Effect | "";
  target_kind?: TargetKind | "";
  refs: KbRefIn[];
}) => call<Hypothesis>("/hypotheses", { method: "POST", body: JSON.stringify(h) });
/** Уже предложенная идея с теми же словами: подсказка автору до отправки. */
export interface SimilarIdea {
  code: string;
  title: string;
  status: HStatus;
  source: "human" | "qwen";
  share: number;
}
export const similarHypotheses = (title: string, statement: string) =>
  call<SimilarIdea[]>("/hypotheses/similar", { method: "POST", body: JSON.stringify({ title, statement }) });
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
