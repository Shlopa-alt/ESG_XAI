import { useQuery } from "@tanstack/react-query";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { kbNetwork, kbTree } from "../api/kb";

// Граф фактов KBRAG. Цвет связи — её направление: это три слота проверенной палитры
// и серый для «прочих»; легенда и текстовая панель фактов дублируют цвет.
const REL_GROUPS = [
  { key: "up", label: "повышает", color: "#1baf7a", match: (r: string) => r.includes("повыша") && !r.startsWith("не ") },
  { key: "down", label: "снижает", color: "#eb6834", match: (r: string) => r.includes("снижа") && !r.startsWith("не ") },
  { key: "none", label: "не влияет", color: "#8a948e", match: (r: string) => r.includes("не влияет") },
  { key: "other", label: "прочие связи", color: "#2a78d6", match: () => true },
] as const;
type RelKey = (typeof REL_GROUPS)[number]["key"];
const MAX_NODES = 250;
const groupOf = (rel: string): (typeof REL_GROUPS)[number] => REL_GROUPS.find((g) => g.match(rel)) ?? REL_GROUPS[3];

interface DatasetFact {
  about: string;
  direction: string;
  relation: string;
  other: string;
  quotes: Array<{ quote: string; doc_id: string; title: string; year: number | null; url: string | null }>;
}

async function kbDataset(name: string, kb: string): Promise<{ name: string; facts: DatasetFact[] }> {
  const res = await fetch(`/api/kb/dataset?${new URLSearchParams({ name, kb }).toString()}`, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`База знаний: ошибка ${res.status}`);
  return (await res.json()) as { name: string; facts: DatasetFact[] };
}

interface ExpLink {
  experiment: string;
  title: string;
  status: string;
  relation: string;
  kbrag_id: string;
}

async function experimentLinks(): Promise<ExpLink[]> {
  const res = await fetch("/api/experiment-links", { credentials: "same-origin" });
  return res.ok ? ((await res.json()) as ExpLink[]) : [];
}

function FactsPanel({ name, kb, onClose }: { name: string; kb: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["kb", "dataset", kb, name], queryFn: () => kbDataset(name, kb) });
  return (
    <aside className="card graph-panel" aria-label={`Факты о ${name}`}>
      <div className="viz-head">
        <div>
          <span className="eyebrow">СУЩНОСТЬ</span>
          <h2 className="h2">{name}</h2>
        </div>
        <button type="button" className="btn-ghost" onClick={onClose}>
          Закрыть
        </button>
      </div>
      {q.isPending && <p className="muted">Загрузка фактов…</p>}
      {q.isError && <p className="error">{q.error.message}</p>}
      <ul className="facts">
        {(q.data?.facts ?? []).map((f, i) => {
          const g = groupOf(f.relation);
          const [from, to] = f.direction === "←" ? [f.other, f.about] : [f.about, f.other];
          return (
            <li key={i}>
              <div className="fact-line">
                <strong>{from}</strong>{" "}
                <span className="rel-tag" style={{ borderColor: g.color }}>
                  {f.relation}
                </span>{" "}
                <strong>{to}</strong>
              </div>
              {f.quotes.slice(0, 2).map((qt) => (
                <blockquote key={qt.doc_id + qt.quote.slice(0, 20)}>
                  «{qt.quote}»
                  <cite>
                    <Link to={`/knowledge/article/${encodeURIComponent(qt.doc_id)}`}>
                      {qt.title}
                      {qt.year ? `, ${qt.year}` : ""}
                    </Link>
                  </cite>
                </blockquote>
              ))}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

export function Graph() {
  const [kb, setKb] = useState("esg");
  const [rels, setRels] = useState<Set<RelKey>>(new Set(["up", "down", "none", "other"]));
  const [minFacts, setMinFacts] = useState(2);
  const [minDraft, setMinDraft] = useState(2); // ползунок: применяется, когда его отпустили
  const [note, setNote] = useState("");
  const [withArticles, setWithArticles] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const tree = useQuery({ queryKey: ["kb", "kbs"], queryFn: () => kbTree("esg") });
  const net = useQuery({ queryKey: ["kb", "network", kb], queryFn: () => kbNetwork(kb) });
  const links = useQuery({ queryKey: ["experiment-links"], queryFn: experimentLinks });
  useEffect(() => {
    const t = window.setTimeout(() => setMinFacts(minDraft), 350);
    return () => window.clearTimeout(t);
  }, [minDraft]);
  useEffect(() => {
    setSelected(null);
    setNote("");
  }, [kb]);

  // Сколько сущностей проходит фильтр и сколько из них показано (раскладка сотен узлов —
  // секунды, тысяч — зависание вкладки)
  const [elements, shownOf] = useMemo<[ElementDefinition[], number]>(() => {
    if (!net.data) return [[], 0];
    const facts = net.data.edges.filter((e) => e.type === "факт" && rels.has(groupOf(e.label ?? "").key));
    const degree = new Map<string, number>();
    for (const e of facts) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + (e.weight ?? 1));
      degree.set(e.target, (degree.get(e.target) ?? 0) + (e.weight ?? 1));
    }
    const passing = [...degree].filter(([, d]) => d >= minFacts).sort((a, b) => b[1] - a[1]);
    const keep = new Set(passing.slice(0, MAX_NODES).map(([id]) => id));
    const out: ElementDefinition[] = [];
    for (const n of net.data.nodes) {
      if (n.kind === "сущность" && keep.has(n.id)) {
        out.push({ data: { id: n.id, label: n.name ?? n.id, kind: "entity", size: 18 + Math.min(40, 6 * (n.facts ?? 1)) } });
      }
    }
    for (const e of facts) {
      if (keep.has(e.source) && keep.has(e.target)) {
        out.push({ data: { id: `${e.source}>${e.target}>${e.label}`, source: e.source, target: e.target, label: e.label, kind: "fact", color: groupOf(e.label ?? "").color } });
      }
    }
    if (withArticles) {
      const articles = new Set<string>();
      for (const e of net.data.edges.filter((x) => x.type === "из статьи" && keep.has(x.target))) {
        articles.add(e.source);
        out.push({ data: { id: `${e.source}>${e.target}`, source: e.source, target: e.target, label: "", color: "#c5cdc8" } });
      }
      for (const n of net.data.nodes.filter((x) => articles.has(x.id))) {
        out.push({ data: { id: n.id, label: (n.name ?? n.id).slice(0, 40), kind: "article", size: 14 } });
      }
      const exps = new Set<string>();
      for (const l of links.data ?? []) {
        const art = `статья:${l.kbrag_id}`;
        if (!articles.has(art)) continue;
        const id = `exp:${l.experiment}`;
        if (!exps.has(id)) {
          exps.add(id);
          out.push({ data: { id, label: l.experiment, kind: "experiment", size: 26 } });
        }
        out.push({ data: { id: `${id}>${art}`, source: id, target: art, label: l.relation, color: "#14231c" } });
      }
    }
    return [out, passing.length];
  }, [net.data, rels, minFacts, withArticles, links.data]);

  useEffect(() => {
    if (!box.current) return undefined;
    const instance = cytoscape({
      container: box.current,
      elements,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        { selector: "node", style: { "background-color": "#2a4a3a", label: "data(label)", width: "data(size)", height: "data(size)", "font-size": 11, color: "#17201b", "text-valign": "bottom", "text-margin-y": 4, "text-wrap": "ellipsis", "text-max-width": "140px", "border-width": 2, "border-color": "#ffffff" } },
        { selector: 'node[kind = "article"]', style: { shape: "round-rectangle", "background-color": "#c5cdc8", "font-size": 9, color: "#5a6b62" } },
        { selector: 'node[kind = "experiment"]', style: { shape: "diamond", "background-color": "#1f6f4a", "font-weight": "bold" } },
        { selector: "edge", style: { width: 2, "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.9 } },
        { selector: "edge:selected, edge.hover", style: { label: "data(label)", "font-size": 10, "text-background-color": "#ffffff", "text-background-opacity": 1, "text-background-padding": "2px" } },
        { selector: ".faded", style: { opacity: 0.12 } },
        { selector: "node:selected", style: { "border-color": "#b5651d", "border-width": 3 } },
      ],
      layout: { name: "cose", animate: false, numIter: 600, nodeRepulsion: () => 9000, idealEdgeLength: () => 90, padding: 20 },
    });
    instance.on("tap", "node", (ev) => {
      const n = ev.target;
      instance.elements().addClass("faded");
      n.closedNeighborhood().removeClass("faded");
      if (n.data("kind") === "entity") setSelected(n.data("label") as string);
    });
    instance.on("tap", (ev) => {
      if (ev.target === instance) {
        instance.elements().removeClass("faded");
        setSelected(null);
      }
    });
    instance.on("mouseover", "edge", (ev) => ev.target.addClass("hover"));
    instance.on("mouseout", "edge", (ev) => ev.target.removeClass("hover"));
    cy.current = instance;
    return () => instance.destroy();
  }, [elements]);

  const focus = () => {
    const c = cy.current;
    const needle = query.trim().toLowerCase();
    if (!c || !needle) return;
    setNote("");
    const found = c.nodes().filter((n) => String(n.data("label")).toLowerCase().includes(needle));
    if (found.length === 0) {
      // на графе не видно — ищем по всей ветке: сущность могла не пройти фильтр
      const hidden = net.data?.nodes.find((n) => n.kind === "сущность" && (n.name ?? "").toLowerCase().includes(needle));
      if (hidden?.name) {
        setSelected(hidden.name);
        setNote(`«${hidden.name}» на графе не видно — её скрывают фильтры. Факты о ней — справа.`);
      } else {
        setNote(`В ветке нет сущности, похожей на «${query.trim()}».`);
      }
      return;
    }
    c.elements().addClass("faded");
    found.closedNeighborhood().removeClass("faded");
    c.fit(found.closedNeighborhood(), 60);
    const first = found[0];
    if (first && first.data("kind") === "entity") setSelected(first.data("label") as string);
  };

  const entities = elements.filter((e) => e.data.kind === "entity").length;
  const edges = elements.filter((e) => e.data.kind === "fact").length;
  const total = net.data?.edges.filter((e) => e.type === "факт").length ?? 0;
  const branches = (tree.data?.nodes ?? []).filter((n) => n.path === "esg" || n.path.startsWith("esg."));
  const toggle = (k: RelKey) => {
    const next = new Set(rels);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setRels(next);
  };

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">БАЗА ЗНАНИЙ · ГРАФ</span>
        <h1 className="page-title">Граф связей</h1>
        <p className="lead">
          Факты из статей: «ESG-фактор → связь → показатель», каждый с дословной цитатой. Щёлкните сущность — справа
          появятся все факты о ней со ссылками на статьи.
        </p>
      </section>
      <div className="card graph-controls">
        <label className="field inline">
          Ветка
          <select value={kb} onChange={(e) => setKb(e.target.value)}>
            {branches.map((b) => (
              <option key={b.path} value={b.path}>
                {"  ".repeat(b.depth)}
                {b.title}
              </option>
            ))}
          </select>
        </label>
        <div className="rel-filters" role="group" aria-label="Какие связи показывать">
          {REL_GROUPS.map((g) => (
            <button key={g.key} type="button" aria-pressed={rels.has(g.key)} className={rels.has(g.key) ? "chip active-rel" : "chip"} onClick={() => toggle(g.key)}>
              <span className="rel-swatch" style={{ background: g.color }} aria-hidden="true" />
              {g.label}
            </button>
          ))}
        </div>
        <label className="field inline">
          Мин. фактов у сущности: {minDraft}
          <input type="range" min={1} max={10} value={minDraft} onChange={(e) => setMinDraft(Number(e.target.value))} />
        </label>
        <label className="check">
          <input type="checkbox" checked={withArticles} onChange={(e) => setWithArticles(e.target.checked)} /> статьи и эксперименты
        </label>
        <form
          className="search-row"
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            focus();
          }}
        >
          <label htmlFor="graph-q" className="sr-only">
            Найти сущность на графе
          </label>
          <input id="graph-q" className="search" placeholder="Найти: ESG disclosure, cost of capital…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button type="submit" className="btn-ghost">
            Найти
          </button>
        </form>
      </div>
      {net.isError && (
        <p className="error" role="alert">
          {net.error.message}
        </p>
      )}
      {net.isSuccess && total === 0 && (
        <div className="card empty-state">
          <h2 className="h2">В этой ветке фактов пока нет</h2>
          <p className="muted">Граф строится моделью по статьям ветки; факты появятся по мере прохода.</p>
        </div>
      )}
      <p className="muted">
        На графе {entities} сущностей и {edges} связей · всего фактов в ветке {total}
        {shownOf > MAX_NODES &&
          ` · фильтр проходят ${shownOf} сущностей, показаны ${MAX_NODES} самых связанных — поднимите порог или найдите сущность`}
      </p>
      {note && (
        <p className="muted" role="status">
          {note}
        </p>
      )}
      <div className={selected ? "graph-layout with-panel" : "graph-layout"}>
        <div ref={box} className="card graph-canvas" role="img" aria-label="Граф фактов: сущности и связи между ними" />
        {selected && <FactsPanel name={selected} kb={kb} onClose={() => setSelected(null)} />}
      </div>
    </>
  );
}
