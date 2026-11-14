// Анализ данных: рекомендация метода по показателю и набору данных, расчёт в один шаг
// (backend/app/api/analysis.py, проект — docs/DATA_ANALYSIS.md)

import type { ParamValue } from "../components/ParamsEditor";

export interface Recommendation {
  key: string;
  template: string;
  title: string;
  method_title: string;
  params: Record<string, unknown>;
  why: string[];
  warnings: string[];
  primary: boolean;
  runnable: boolean;
  net: string;
  as_authors: boolean;
  evidence: string;
}

export interface AuthorsNet {
  net: string;
  title: string;
  quote: string;
  runnable: boolean;
  nearest_title: string;
  article_title: string;
  doc_id: string;
}

export interface RecommendOut {
  snapshot: { id: number; dataset: string; title: string; version: string };
  columns: string[];
  numeric: string[];
  categories: string[];
  sheet: string;
  sheets: string[];
  rows: number | null;
  target_candidates: Array<{ column: string; reason: string }>;
  task: { key: string; title: string; text: string };
  recommendations: Recommendation[];
  authors: AuthorsNet | null;
  authors_note: string;
  hypothesis: { code: string; title: string; statement: string; status: string; node: string } | null;
}

export interface Catalog {
  tasks: Array<{ key: string; title: string; example: string; nets: string[] }>;
  nets: Array<{ key: string; title: string; family: string; runnable: boolean; nearest: string }>;
}

export interface Choice {
  key: string;
  title: string;
  why: string[];
  primary: boolean;
  net: string;
  as_authors: boolean;
  evidence: string;
  article: string;
  task: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

export const getCatalog = () => call<Catalog>("/analysis/catalog");

export const recommend = (b: { snapshot_id: number; sheet: string; target: string; node: string; hypothesis: string }) =>
  call<RecommendOut>("/analysis/recommend", { method: "POST", body: JSON.stringify(b) });

export const launchAnalysis = (b: {
  snapshot_id: number;
  template: string;
  params: Record<string, ParamValue>;
  node: string;
  hypothesis: string;
  choice: Choice;
}) => call<{ experiment: string; run_id: number }>("/analysis/launch", { method: "POST", body: JSON.stringify(b) });
