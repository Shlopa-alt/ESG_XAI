// Черновики датасетов из таблиц статей KBRAG (backend/app/api/data_drafts.py)

export type DraftStatus = "proposed" | "approved" | "rejected";
export type Cell = number | string | null;

export interface DraftItem {
  id: number;
  status: DraftStatus;
  title: string;
  article_title: string;
  doi: string;
  doc_id: string;
  table_number: number;
  page: number | null;
  n_rows: number;
  n_cols: number;
  dataset: string;
  created_at: string;
}

export interface DraftHistory {
  at: string;
  who: string;
  kind: "parse" | "manual" | "qwen" | "command" | "approve" | "reject";
  text: string;
}

export interface DraftJob {
  id: number;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  command: string;
  message: string;
}

export interface Draft extends DraftItem {
  kb_path: string;
  caption: string;
  description: string;
  columns: string[];
  rows: Cell[][];
  numeric: string[];
  history: DraftHistory[];
  note: string;
  decided_by: string;
  decided_at: string | null;
  jobs: DraftJob[];
}

/** Операция правки — те же, что выбирает Qwen по команде (backend/app/services/data_drafts.py). */
export type DraftOp =
  | { op: "rename"; column: string; to: string }
  | { op: "drop_columns"; columns: string[] }
  | { op: "drop_rows"; rows: number[] }
  | { op: "set_cell"; row: number; column: string; value: string }
  | { op: "to_number"; column: string };

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

export const listDrafts = (status: DraftStatus | "all") => call<DraftItem[]>(`/data-drafts?status=${status}`);
export const getDraft = (id: number) => call<Draft>(`/data-drafts/${id}`);
export const editDraft = (id: number, body: { title?: string; description?: string; ops?: DraftOp[] }) =>
  call<Draft>(`/data-drafts/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const commandDraft = (id: number, text: string) =>
  call<Draft>(`/data-drafts/${id}/command`, { method: "POST", body: JSON.stringify({ text }) });
export const approveDraft = (id: number, body: { title: string; description: string; access_level: "public" | "nda" }) =>
  call<Draft>(`/data-drafts/${id}/approve`, { method: "POST", body: JSON.stringify(body) });
export const rejectDraft = (id: number, note: string) =>
  call<Draft>(`/data-drafts/${id}/reject`, { method: "POST", body: JSON.stringify({ note }) });
export const scanTables = (docId = "") =>
  call<{ job: number }>("/data-drafts/scan", { method: "POST", body: JSON.stringify({ doc_id: docId }) });

export const DRAFT_STATUS: Record<DraftStatus, string> = {
  proposed: "ждёт решения",
  approved: "датасет создан",
  rejected: "отклонён",
};

export const DRAFT_BADGE: Record<DraftStatus, string> = {
  proposed: "st-review",
  approved: "st-done",
  rejected: "st-planned",
};

export const JOB_STATUS: Record<DraftJob["status"], string> = {
  queued: "в очереди",
  running: "Qwen думает",
  done: "готово",
  failed: "ошибка",
  cancelled: "снята",
};
