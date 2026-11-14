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
}

export interface Choice {
  key: string;
  title: string;
  why: string[];
  primary: boolean;
  net: string;
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

export const recommend = (b: { snapshot_id: number; sheet: string; target: string; node: string }) =>
  call<RecommendOut>("/analysis/recommend", { method: "POST", body: JSON.stringify(b) });

export const launchAnalysis = (b: {
  snapshot_id: number;
  template: string;
  params: Record<string, ParamValue>;
  node: string;
  choice: Choice;
}) => call<{ experiment: string; run_id: number }>("/analysis/launch", { method: "POST", body: JSON.stringify(b) });
