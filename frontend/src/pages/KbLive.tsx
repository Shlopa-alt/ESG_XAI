import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { kbDocuments, kbNetwork, kbSearch, kbStats, kbTree } from "../api/kb";

const ROOT = "esg";
const fmt = (n: number) => n.toLocaleString("ru-RU");

/** Выбор ветки дерева esg.* базы знаний. */
function BranchSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const tree = useQuery({ queryKey: ["kb", "kbs"], queryFn: () => kbTree(ROOT) });
  const nodes = (tree.data?.nodes ?? []).filter((n) => n.path === ROOT || n.path.startsWith(`${ROOT}.`));
  return (
    <label className="field inline">
      Ветка базы знаний
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {nodes.length === 0 && <option value={ROOT}>ESG</option>}
        {nodes.map((n) => (
          <option key={n.path} value={n.path}>
            {"  ".repeat(n.depth)}
            {n.title} ({n.subtree ?? 0})
          </option>
        ))}
      </select>
    </label>
  );
}

/** Поиск, статьи и сводка базы знаний KBRAG — живые данные через /api/kb/*. */
export function KbLive() {
  const [kb, setKb] = useState(ROOT);
  // Запрос живёт в адресе (?q=): сюда ведёт и поиск из шапки
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const stats = useQuery({ queryKey: ["kb", "stats", kb], queryFn: () => kbStats(kb) });
  const docs = useQuery({ queryKey: ["kb", "docs", kb], queryFn: () => kbDocuments(kb) });
  const hits = useQuery({ queryKey: ["kb", "search", kb, q], queryFn: () => kbSearch(q, kb), enabled: q !== "" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next = draft.trim();
    setParams(next ? { q: next } : {});
  };

  if (stats.isError) {
    return (
      <section className="card">
        <h2 className="h2">База знаний KBRAG</h2>
        <p className="error" role="alert">
          {stats.error.message}
        </p>
      </section>
    );
  }

  return (
    <section className="card kb-live">
      <div className="kb-live-head">
        <div>
          <h2 className="h2">База знаний KBRAG</h2>
          <p className="muted">
            {stats.data
              ? `${stats.data.kb_title}: ${fmt(stats.data.documents)} статей, ${fmt(stats.data.chunks)} фрагментов` +
                (stats.data.year_from ? `, ${stats.data.year_from}–${stats.data.year_to}` : "")
              : "Загрузка…"}
          </p>
        </div>
        <BranchSelect value={kb} onChange={setKb} />
      </div>

      <form className="search-row" onSubmit={submit} role="search">
        <label htmlFor="kb-q" className="sr-only">
          Поиск по статьям базы знаний
        </label>
        <input
          id="kb-q"
          type="search"
          className="search"
          placeholder="Например: ESG и ROA, расхождение ESG-рейтингов, SHAP…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className="btn-primary">
          Найти
        </button>
      </form>

      {q !== "" && (
        <div className="hits">
          {hits.isPending && <p className="muted">Ищу…</p>}
          {hits.isError && (
            <p className="error" role="alert">
              {hits.error.message}
            </p>
          )}
          {hits.data?.length === 0 && <p className="muted">Ничего не найдено.</p>}
          {hits.data?.map((h) => (
            <article key={h.chunk_id} className="hit">
              <div className="kb-meta">
                <span className="mono">{h.year ?? "—"}</span> ·{" "}
                {h.url ? (
                  <a href={h.url} target="_blank" rel="noreferrer">
                    {h.title}
                  </a>
                ) : (
                  h.title
                )}
                {h.pages.length > 0 && <span> · с. {h.pages.join(", ")}</span>}
              </div>
              {h.headings.length > 0 && <div className="muted">{h.headings.join(" › ")}</div>}
              <p className="hit-text">{h.text.length > 600 ? `${h.text.slice(0, 600)}…` : h.text}</p>
            </article>
          ))}
        </div>
      )}

      <details className="docs">
        <summary>Статьи ветки ({docs.data?.length ?? "…"})</summary>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Год</th>
              <th scope="col">Статья</th>
              <th scope="col" className="num">Фрагментов</th>
            </tr>
          </thead>
          <tbody>
            {docs.data?.map((d) => (
              <tr key={d.doc_id}>
                <td className="mono">{d.year ?? "—"}</td>
                <td>
                  {d.url ? (
                    <a href={d.url} target="_blank" rel="noreferrer">
                      {d.title || d.doc_id}
                    </a>
                  ) : (
                    d.title || d.doc_id
                  )}
                </td>
                <td className="num mono">{d.chunks}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

/** Сводка графа фактов KBRAG; визуализация — когда граф построен. */
export function KbGraphSummary() {
  const net = useQuery({ queryKey: ["kb", "network", ROOT], queryFn: () => kbNetwork(ROOT) });
  if (net.isPending) return <div className="card muted">Загрузка графа…</div>;
  if (net.isError) {
    return (
      <div className="card error" role="alert">
        {net.error.message}
      </div>
    );
  }
  const entities = net.data.nodes.filter((n) => n.kind === "сущность");
  const facts = net.data.edges.filter((e) => e.type === "факт");
  if (facts.length === 0) {
    return (
      <div className="card">
        <h2 className="h2">Граф фактов</h2>
        <p className="muted">
          Граф ещё не построен: статьи загружены, фактов пока нет. Граф выписывает языковая модель Qwen3 по правилам
          ветки esg — следующий шаг после загрузки модели.
        </p>
      </div>
    );
  }
  const top = [...entities].sort((a, b) => (b.facts ?? 0) - (a.facts ?? 0)).slice(0, 30);
  return (
    <div className="card">
      <h2 className="h2">
        Граф фактов: {fmt(entities.length)} сущностей, {fmt(facts.length)} связей
      </h2>
      <ul className="list">
        {top.map((n) => (
          <li key={n.id}>
            {n.name} <span className="muted">— фактов {n.facts ?? 0}, статей {n.documents ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
