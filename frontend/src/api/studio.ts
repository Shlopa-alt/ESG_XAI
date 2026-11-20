/** Студия: сценарии из узлов (замена Loginom), расчёт и предпросмотр — backend/app/api/studio.py. */

export interface ParamSchema {
  name: string;
  label: string;
  kind: "snapshot" | "text" | "number" | "bool" | "select" | "multiselect" | "column" | "columns" | "expr" | "rows";
  required: boolean;
  default?: unknown;
  options?: { value: string; label: string }[];
  fields?: ParamSchema[];
  from_port?: string;
  hint?: string;
}

export interface ComponentSchema {
  type: string;
  title: string;
  group: string;
  description: string;
  inputs: { name: string; label: string; optional?: boolean }[];
  params: ParamSchema[];
}

export interface GraphNode {
  id: string;
  type: string;
  title?: string;
  params: Record<string, unknown>;
  x: number;
  y: number;
}

export interface GraphEdge {
  from: string;
  to: string;
  port: string;
}

export interface Graph {
  format: 1;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ScenarioBrief {
  code: string;
  title: string;
  description: string;
  version: number;
  author: string;
  nodes: number;
  updated_at: string;
}

export interface RowsView {
  columns: { name: string; kind: string }[];
  rows: unknown[][];
  total: number;
}

export interface QualityColumn {
  name: string;
  kind: string;
  missing: number;
  missing_share: number;
  unique: number;
  zeros?: number;
  negative?: number;
  outliers?: number;
  problems: string[];
}

export interface NodeView {
  table?: RowsView;
  statistics?: { rows: number; columns: ColumnStats[] };
  quality?: { rows: number; duplicate_rows: number; issues: number; columns: QualityColumn[] };
  sample?: RowsView; // выборка для «Диаграммы» — у узла, посчитанного предпросмотром
  report?: ModelReport; // «Отчёт» модели Data Mining
}

export interface ModelReport {
  kind: string;
  title: string;
  metrics?: { name: string; train: number | null; test: number | null; cv: number | null }[];
  summary?: [string, unknown][];
  tables?: { title: string; columns: string[]; rows: unknown[][] }[];
  roc?: { fpr: number; tpr: number }[];
  notes?: string[];
}

export interface ColumnStats {
  name: string;
  kind: string;
  count: number;
  missing: number;
  unique: number;
  min?: number | string | null;
  max?: number | string | null;
  mean?: number | null;
  std?: number | null;
  median?: number | null;
  q1?: number | null;
  q3?: number | null;
  top?: { value: string; count: number }[];
  histogram?: { from: number; to: number; count: number }[];
}

export interface NodeSummary {
  ok: boolean;
  error: string;
  rows?: number;
  cols?: number;
  seconds: number;
  skipped: boolean;
}

export interface StudioRun {
  id: number;
  version: number;
  until: string;
  status: "queued" | "running" | "done" | "failed" | "stopped";
  message: string;
  created_at: string;
  finished_at: string | null;
  summary: { nodes?: Record<string, NodeSummary>; error?: { node: string; message: string } };
  files: string[];
  views?: Record<string, NodeView>;
  hidden: boolean;
  runner_commit: string;
}

export interface Scenario extends ScenarioBrief {
  graph: Graph;
  editable: boolean;
  runs: StudioRun[];
}

export class StudioError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly node: string = "",
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/studio${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    const d = body?.detail;
    if (d && typeof d === "object" && "message" in d) {
      const o = d as { message: string; node?: string };
      throw new StudioError(o.message, res.status, o.node ?? "");
    }
    throw new StudioError(typeof d === "string" ? d : res.statusText, res.status);
  }
  return (await res.json()) as T;
}

export const getComponents = () => call<{ format: number; components: ComponentSchema[] }>("/components");
export const listScenarios = () => call<ScenarioBrief[]>("/scenarios");
export const createScenario = (title: string, description = "") =>
  call<ScenarioBrief>("/scenarios", { method: "POST", body: JSON.stringify({ title, description }) });
export const getScenario = (code: string) => call<Scenario>(`/scenarios/${encodeURIComponent(code)}`);
export const saveScenario = (code: string, version: number, graph: Graph, title?: string) =>
  call<Scenario>(`/scenarios/${encodeURIComponent(code)}`, {
    method: "PUT",
    body: JSON.stringify({ version, graph, ...(title ? { title } : {}) }),
  });
export const copyScenario = (code: string) =>
  call<ScenarioBrief>(`/scenarios/${encodeURIComponent(code)}/copy`, { method: "POST" });
export const runScenario = (code: string, until = "") =>
  call<StudioRun>(`/scenarios/${encodeURIComponent(code)}/run`, { method: "POST", body: JSON.stringify({ until }) });
export const getRun = (id: number) => call<StudioRun>(`/runs/${id}`);
export const stopRun = (id: number) => call<StudioRun>(`/runs/${id}/stop`, { method: "POST" });
export const fileUrl = (id: number, name: string) => `/api/studio/runs/${id}/files/${encodeURIComponent(name)}`;
