export type Stability = "stable" | "draft" | "contested";
export type CrStatus = "proposed" | "review" | "accepted" | "rejected";

export interface Section {
  number: string;
  title: string;
  content: string;
  stability: Stability;
}

export interface ChangeRequest {
  code: string;
  section: string;
  section_title: string;
  title: string;
  description: string;
  proposed_content: string;
  status: CrStatus;
  target_version: string;
  bases: Array<{ basis_type: string; ref: string; valid: boolean }>;
  reviews: Array<{ reviewer: string; verdict: "approve" | "changes" | "reject"; text: string; created_at: string }>;
  blockers: string[];
}

export interface Version {
  version: string;
  notes: string;
  created_at: string;
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

export const getMethodology = () => call<{ version: string | null; sections: Section[] }>("/methodology");
export const listVersions = () => call<Version[]>("/methodology/versions");
export const listCrs = () => call<ChangeRequest[]>("/change-requests");
export const reviewCr = (code: string, verdict: string, text: string) =>
  call<ChangeRequest>(`/change-requests/${code}/reviews`, { method: "POST", body: JSON.stringify({ verdict, text }) });
export const setCrStatus = (code: string, status: "review" | "accepted" | "rejected") =>
  call<ChangeRequest>(`/change-requests/${code}`, { method: "PATCH", body: JSON.stringify({ status }) });

export const STABILITY_LABEL: Record<Stability, string> = {
  stable: "устойчив",
  draft: "черновик",
  contested: "оспаривается",
};

export const CR_STATUS_LABEL: Record<CrStatus, string> = {
  proposed: "предложено",
  review: "на рецензии",
  accepted: "принято",
  rejected: "отклонено",
};
export const createCr = (cr: { section: string; title: string; description: string; proposed_content: string }) =>
  call<ChangeRequest>("/change-requests", { method: "POST", body: JSON.stringify(cr) });
export const addCrBasis = (code: string, experimentCode: string) =>
  call<ChangeRequest>(`/change-requests/${code}/bases`, {
    method: "POST",
    body: JSON.stringify({ basis_type: "experiment", experiment_code: experimentCode }),
  });
