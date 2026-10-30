// База знаний KBRAG через прокси платформы /api/kb/* (backend/app/api/kb.py).

export interface KbStats {
  kb: string;
  kb_title: string;
  documents: number;
  chunks: number;
  year_from: number | null;
  year_to: number | null;
}

export interface KbNode {
  path: string;
  title: string;
  depth: number;
  own: number | null;
  subtree: number | null;
  in_db: boolean;
}

export interface KbTree {
  nodes: KbNode[];
  current: string;
  title: string;
  examples: string[];
}

export interface KbHit {
  chunk_id: number;
  doc_id: string;
  ord: number;
  title: string;
  year: number | null;
  journal: string | null;
  url: string | null;
  authors: string[];
  headings: string[];
  pages: number[];
  text: string;
  score: number;
}

export interface KbDocument {
  doc_id: string;
  title: string | null;
  year: number | null;
  journal: string | null;
  url: string | null;
  authors: string[] | null;
  chunks: number;
}

export interface KbNetwork {
  nodes: Array<{ id: string; kind: string; name?: string; facts?: number; documents?: number }>;
  edges: Array<{ source: string; target: string; type: string; label?: string; weight?: number }>;
}

async function get<T>(name: string, params: Record<string, string>): Promise<T> {
  const res = await fetch(`/api/kb/${name}?${new URLSearchParams(params).toString()}`, {
    credentials: "same-origin",
  });
  const body = (await res.json().catch(() => null)) as (T & { error?: string; detail?: string }) | null;
  if (!res.ok || body === null) {
    throw new Error(body?.detail ?? body?.error ?? `База знаний: ошибка ${res.status}`);
  }
  return body;
}

export const kbStats = (kb: string) => get<KbStats>("stats", { kb });
export const kbTree = (kb: string) => get<KbTree>("kbs", { kb });
export const kbSearch = (q: string, kb: string) =>
  get<{ hits: KbHit[] }>("search", { q, kb, limit: "12" }).then((r) => r.hits);
export const kbDocuments = (kb: string) =>
  get<{ documents: KbDocument[] }>("documents", { kb }).then((r) => r.documents);
export const kbNetwork = (kb: string) => get<KbNetwork>("network", { kb });
