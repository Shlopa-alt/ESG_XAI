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
  measures?: string[]; // числовые столбцы-величины: без идентификаторов и кодов отрасли
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
  expected: string; // по идее — что подтвердит или опровергнет её
  choice: Choice;
}) => call<{ experiment: string; run_id: number }>("/analysis/launch", { method: "POST", body: JSON.stringify(b) });

// «Нейросети»: найденная связь → набор сетей → сравнение (backend/app/api/analysis.py: links, link_check)
export interface NetResult {
  run_id: number | null; // null — сеть не запускалась (не уложилась в лимит метода)
  status: string; // queued | running | done | failed | stopped | skipped
  net: string; // mlp | transformer | gbm | linear
  title: string;
  r2: number | null; // R² на данных, которых не было в обучении
  placebo: number | null; // R² на перемешанной цели (связи нет по построению)
  holds: boolean | null; // null — расчёт ещё не закончен или сеть не запускалась
  reason?: string; // почему не запускалась
}

export interface LinkCheck {
  experiment: string;
  a: string;
  b: string;
  target: string;
  nets: NetResult[];
  held: number;
  finished: number;
  total: number;
}

export interface ScanOut {
  run_id: number;
  status: string;
  message: string;
  group: string;
  unit: "group" | "row" | null;
  rows_find: number | null;
  rows_confirm: number | null;
  pairs: number | null;
  found: number | null;
  confirmed: number | null;
  panel_hint: string | null;
  not_confirmed_total: number | null;
  links_total: number | null;
  // kind: монотонная | немонотонная (способ rank), линейная (linear), частная (partial)
  links: Array<{ a: string; b: string; kind: string; rho: number; xi: number; rho_confirm: number | null; xi_confirm: number | null; n: number }>;
  method?: LinkMethod;
}

/** Способ поиска связей (runner/methods/correlation_scan.py: METHODS) */
export type LinkMethod = "rank" | "linear" | "partial";

export interface LinksOut {
  snapshot: { id: number; dataset: string; title: string; version: string };
  scan: ScanOut | null;
  checks: LinkCheck[];
  // последний поиск каждым способом — чтобы сравнить, что нашли разные способы
  scans?: Array<{ method: LinkMethod; run_id: number; status: string; confirmed: number | null; pairs: number | null }>;
}

export const getLinks = (snapshotId: number, method: LinkMethod | "" = "") =>
  call<LinksOut>(`/analysis/links?snapshot_id=${snapshotId}${method ? `&method=${method}` : ""}`);

export interface LinkTarget {
  scan_run: number;
  a: string;
  b: string;
  target: string; // a или b — что предсказываем
  node: string;
}

/** Сеть, которую можно выбрать для проверки связи (POST /analysis/link-nets) */
export interface NetOption {
  id: string; // mlp | transformer | gbm | method:M-NN
  net: string;
  title: string;
  minutes: number | null; // оценка времени расчёта
  note: string;
  runnable: boolean;
  warnings: string[];
  recommended: boolean;
  done: boolean; // уже считалась в проверке этой связи
}

export const linkNets = (b: LinkTarget) =>
  call<{ nets: NetOption[]; existing: string | null; existing_status: string | null }>("/analysis/link-nets", {
    method: "POST",
    body: JSON.stringify(b),
  });

export const checkLink = (b: LinkTarget & { nets?: string[] }) =>
  call<{ experiment: string; run_ids: number[]; added?: boolean }>("/analysis/link-check", { method: "POST", body: JSON.stringify(b) });
