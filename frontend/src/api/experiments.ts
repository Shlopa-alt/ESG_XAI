export type ExpStatus = "draft" | "planned" | "running" | "review" | "done" | "failed";
export type Outcome = "confirmed" | "rejected" | "inconclusive";

export interface Experiment {
  code: string;
  title: string;
  hypothesis: string;
  direction: string;
  status: ExpStatus;
  outcome: Outcome | null;
  method: string;
  data_summary: string;
  dataset_snapshot_id: number | null;
  seed: number | null;
  runner_commit: string;
  env_lock: string;
  setup: string[];
  results: string[];
  conclusion: string;
  limitations: string[];
  reproducibility: string[];
  report_path: string;
  report?: Record<string, unknown>;
}

export interface ExperimentDetail extends Experiment {
  reviews: Array<{ id: number; reviewer: string; verdict: "approve" | "changes" | "reject"; text: string; created_at: string }>;
  links: Array<{ relation: string; kind: string; kbrag_id: string; title: string; doi: string; quote: string }>;
}

export interface Dataset {
  code: string;
  title: string;
  description: string;
  source_url: string;
  access_level: "public" | "nda";
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

export const listExperiments = () => call<Experiment[]>("/experiments");
export const getExperiment = (code: string) => call<ExperimentDetail>(`/experiments/${code}`);
export const listDatasets = () => call<Dataset[]>("/datasets");
export const addReview = (code: string, verdict: string, text: string) =>
  call<ExperimentDetail>("/reviews", {
    method: "POST",
    body: JSON.stringify({ target_code: code, verdict, text }),
  });

export const STATUS_LABEL: Record<ExpStatus, string> = {
  draft: "черновик",
  planned: "запланирован",
  running: "в работе",
  review: "на проверке",
  done: "завершён",
  failed: "сбой",
};

export const OUTCOME_LABEL: Record<Outcome, string> = {
  confirmed: "гипотеза подтверждена",
  rejected: "гипотеза отклонена",
  inconclusive: "результат неоднозначен",
};

export const VERDICT_LABEL = { approve: "одобрено", changes: "нужны правки", reject: "отклонено" } as const;
