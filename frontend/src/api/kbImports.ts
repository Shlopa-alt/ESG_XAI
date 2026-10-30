// Импорт статей в базу знаний через сайт: PDF-файлом или по DOI; разбирает обработчик на машине KBRAG.

export type ImportStatus = "queued" | "processing" | "done" | "duplicate" | "failed";

export interface KbImport {
  id: number;
  kb_path: string;
  source: "file" | "doi";
  filename: string;
  doi: string;
  title: string;
  year: number | null;
  authors: string[];
  bytes_len: number;
  status: ImportStatus;
  doc_id: string;
  message: string;
  author: string;
  created_at: string;
  finished_at: string | null;
}

export const IMPORT_STATUS: Record<ImportStatus, string> = {
  queued: "в очереди",
  processing: "разбирается",
  done: "в базе знаний",
  duplicate: "уже была в базе",
  failed: "не удалось",
};

export const IMPORT_BADGE: Record<ImportStatus, string> = {
  queued: "st-planned",
  processing: "st-running",
  done: "st-done",
  duplicate: "st-review",
  failed: "st-failed",
};

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/kb-imports${path}`, { credentials: "same-origin", ...init });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) {
    const d = body?.detail;
    if (res.status === 413) throw new Error("Файл слишком большой");
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? "Проверьте поля формы" : `Ошибка ${res.status}`);
  }
  return body;
}

export const listImports = () => send<KbImport[]>("");

export interface UploadFields {
  file: File;
  kb_path: string;
  doi: string;
  title: string;
  year: string;
  authors: string;
}

export function uploadPdf(f: UploadFields): Promise<KbImport> {
  const form = new FormData();
  for (const [k, v] of Object.entries(f)) form.append(k, v as string | Blob);
  return send<KbImport>("", { method: "POST", body: form });
}

export const importByDoi = (doi: string, kb_path: string) =>
  send<KbImport>("/doi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doi, kb_path }),
  });

export const retryImport = (id: number) => send<KbImport>(`/${id}/retry`, { method: "POST" });
