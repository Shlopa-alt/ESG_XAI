// Библиотека методов: встроенные и методы из статей банка (backend/app/api/methods.py)

export type MethodStatus = "ready" | "failed" | "enabled" | "rejected";

export interface LibraryMethod {
  code: string;
  key: string; // ключ в библиотеке расчётов: method:M-01
  title: string;
  description: string;
  net: string;
  net_title: string;
  task: string;
  params: Array<{ name: string; label: string; default: number; min: number; max: number; hint: string }>;
  status: MethodStatus;
  check_log: string;
  sha256: string;
  doc_id: string;
  article_title: string;
  doi: string;
  evidence: string;
  author: string;
  decided_by: string;
  decision_note: string;
  created_at: string;
  script: string; // только в карточке метода
}

export interface Library {
  builtin: Array<{ key: string; title: string; description: string }>;
  methods: LibraryMethod[];
  pending: Array<{ job: number; doc_id: string; status: string }>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...init });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

export const getLibrary = () => call<Library>("/methods");
export const getMethod = (code: string) => call<LibraryMethod>(`/methods/${encodeURIComponent(code)}`);
export const methodFromArticle = (docId: string) =>
  call<{ job: number }>("/methods/from-article", { method: "POST", body: JSON.stringify({ doc_id: docId }) });
export const enableMethod = (code: string) => call<LibraryMethod>(`/methods/${encodeURIComponent(code)}/enable`, { method: "POST" });
export const rejectMethod = (code: string, note: string) =>
  call<LibraryMethod>(`/methods/${encodeURIComponent(code)}/reject`, { method: "POST", body: JSON.stringify({ note }) });
