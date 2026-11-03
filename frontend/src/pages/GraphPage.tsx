import { useQuery } from "@tanstack/react-query";
import cytoscape, { type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { type KbNetwork, kbNetwork, kbTree } from "../api/kb";

// Граф фактов KBRAG. Цвет связи — её направление: это три слота проверенной палитры
// и серый для «прочих»; легенда и текстовая панель фактов дублируют цвет.
const REL_GROUPS = [
  { key: "up", label: "повышает", color: "#1baf7a", match: (r: string) => r.includes("повыша") && !r.startsWith("не ") },
  { key: "down", label: "снижает", color: "#eb6834", match: (r: string) => r.includes("снижа") && !r.startsWith("не ") },
  { key: "none", label: "не влияет", color: "#8a948e", match: (r: string) => r.includes("не влияет") },
  { key: "other", label: "прочие связи", color: "#2a78d6", match: () => true },
] as const;
type RelKey = (typeof REL_GROUPS)[number]["key"];
// Обзор: N самых связанных сущностей (ползунок) и вдвое больше линий — самых весомых; между
// парой сущностей одна линия. После полного прохода модели у ветки esg тысячи сущностей и
// десятки тысяч связей: всё сразу — неразличимый клубок. Подробности — в окрестности сущности:
// она в центре, вокруг её самые весомые соседи.
const NEIGHBOURS = 30;
const EDGES_PER_NODE = 2;
// Фактов у сущности от 1 до тысяч, статей у связи — от 1 до десятков: размеры по логарифму
const nodeSize = (facts: number) => Math.min(46, 12 + 4 * Math.log2(Math.max(1, facts)));
const edgeWidth = (weight: number) => Math.min(6, 1 + 1.5 * Math.log2(Math.max(1, weight)));
type Fact = KbNetwork["edges"][number];
const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);

/** Одна линия на пару сущностей — самая весомая связь; самые весомые пары первыми. */
function strongestPairs(facts: Fact[], keep: (e: Fact) => boolean): Fact[] {
  const best = new Map<string, Fact>();
  for (const e of facts) {
    if (!keep(e)) continue;
    const k = pairKey(e.source, e.target);
    const was = best.get(k);
    if (!was || (e.weight ?? 1) > (was.weight ?? 1)) best.set(k, e);
  }
  return [...best.values()].sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1));
}
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

function FactsPanel({ name, kb, onClose, onFocus }: { name: string; kb: string; onClose: () => void; onFocus?: () => void }) {
  const q = useQuery({ queryKey: ["kb", "dataset", kb, name], queryFn: () => kbDataset(name, kb) });
  return (
    <aside className="card graph-panel" aria-label={`Факты о ${name}`}>
      <div className="viz-head">
        <div>
          <span className="eyebrow">СУЩНОСТЬ</span>
          <h2 className="h2">{name}</h2>
        </div>
        <div className="actions">
          {onFocus && (
            <button type="button" className="btn-ghost" onClick={onFocus}>
              Окрестность на графе
            </button>
          )}
          <button type="button" className="btn-ghost" onClick={onClose}>
            Закрыть
          </button>
        </div>
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
  const [size, setSize] = useState(50);
  const [sizeDraft, setSizeDraft] = useState(50); // ползунок: применяется, когда его отпустили
  const [center, setCenter] = useState<string | null>(null); // id сущности — режим «окрестность»
  const [note, setNote] = useState("");
  const [withArticles, setWithArticles] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const tree = useQuery({ queryKey: ["kb", "kbs"], queryFn: () => kbTree("esg") });
  const net = useQuery({ queryKey: ["kb", "network", kb], queryFn: () => kbNetwork(kb) });
  const links = useQuery({ queryKey: ["experiment-links"], queryFn: experimentLinks });
  useEffect(() => {
    const t = window.setTimeout(() => setSize(sizeDraft), 350);
    return () => window.clearTimeout(t);
  }, [sizeDraft]);
  useEffect(() => {
    setSelected(null);
    setCenter(null);
    setNote("");
  }, [kb]);

  const entityNodes = useMemo(() => (net.data?.nodes ?? []).filter((n) => n.kind === "сущность"), [net.data]);
  const nameOf = (id: string | null) => entityNodes.find((n) => n.id === id)?.name ?? id ?? "";
  const idOf = (name: string) => entityNodes.find((n) => n.name === name)?.id ?? null;

  const view = useMemo(() => {
    const out: ElementDefinition[] = [];
    if (!net.data) return { elements: out, entitiesTotal: 0, hidden: 0, around: 0 };
    const facts = net.data.edges.filter((e) => e.type === "факт" && rels.has(groupOf(e.label ?? "").key));
    const degree = new Map<string, number>();
    for (const e of facts) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + (e.weight ?? 1));
      degree.set(e.target, (degree.get(e.target) ?? 0) + (e.weight ?? 1));
    }
    let drawn: Fact[];
    let hidden: number;
    let around = 0;
    if (center) {
      const touching = strongestPairs(facts, (e) => e.source === center || e.target === center);
      const top = touching.slice(0, NEIGHBOURS);
      const ring = new Set(top.flatMap((e) => [e.source, e.target]));
      const between = strongestPairs(
        facts,
        (e) => e.source !== center && e.target !== center && ring.has(e.source) && ring.has(e.target),
      );
      drawn = [...top, ...between.slice(0, NEIGHBOURS)];
      around = touching.length;
      hidden = touching.length - top.length;
    } else {
      const keep = new Set(
        [...degree]
          .sort((a, b) => b[1] - a[1])
          .slice(0, size)
          .map(([id]) => id),
      );
      const among = strongestPairs(facts, (e) => keep.has(e.source) && keep.has(e.target));
      drawn = among.slice(0, size * EDGES_PER_NODE);
      hidden = among.length - drawn.length;
    }
    const linked = new Set(drawn.flatMap((e) => [e.source, e.target]));
    if (center) linked.add(center);
    for (const n of net.data.nodes) {
      if (n.kind === "сущность" && linked.has(n.id)) {
        out.push({ data: { id: n.id, label: n.name ?? n.id, kind: "entity", size: nodeSize(n.facts ?? 1), center: n.id === center ? "yes" : "no" } });
      }
    }
    for (const e of drawn) {
      out.push({
        data: { id: `${e.source}>${e.target}>${e.label}`, source: e.source, target: e.target, label: e.label, kind: "fact", color: groupOf(e.label ?? "").color, width: edgeWidth(e.weight ?? 1) },
      });
    }
    if (withArticles) {
      const articles = new Set<string>();
      for (const e of net.data.edges.filter((x) => x.type === "из статьи" && linked.has(x.target))) {
        articles.add(e.source);
        out.push({ data: { id: `${e.source}>${e.target}`, source: e.source, target: e.target, label: "", color: "#c5cdc8", width: 1 } });
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
        out.push({ data: { id: `${id}>${art}`, source: id, target: art, label: l.relation, color: "#14231c", width: 2 } });
      }
    }
    return { elements: out, entitiesTotal: degree.size, hidden, around };
  }, [net.data, rels, size, center, withArticles, links.data]);

  useEffect(() => {
    if (!box.current) return undefined;
    const instance = cytoscape({
      container: box.current,
      elements: view.elements,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#2a4a3a",
            label: "data(label)",
            width: "data(size)",
            height: "data(size)",
            "font-size": 11,
            "min-zoomed-font-size": 7,
            color: "#17201b",
            "text-valign": "bottom",
            "text-margin-y": 3,
            "text-wrap": "ellipsis",
            "text-max-width": "130px",
            "text-outline-color": "#ffffff",
            "text-outline-width": 2,
            "border-width": 1.5,
            "border-color": "#ffffff",
          },
        },
        { selector: 'node[center = "yes"]', style: { "background-color": "#b5651d", "font-size": 13, "font-weight": "bold" } },
        { selector: 'node[kind = "article"]', style: { shape: "round-rectangle", "background-color": "#c5cdc8", "font-size": 9, color: "#5a6b62" } },
        { selector: 'node[kind = "experiment"]', style: { shape: "diamond", "background-color": "#1f6f4a", "font-weight": "bold" } },
        {
          selector: "edge",
          style: { width: "data(width)", "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.7, opacity: 0.6 },
        },
        { selector: "edge:selected, edge.hover", style: { opacity: 1, label: "data(label)", "font-size": 10, "text-background-color": "#ffffff", "text-background-opacity": 1, "text-background-padding": "2px" } },
        { selector: ".faded", style: { opacity: 0.1 } },
        { selector: "node:selected", style: { "border-color": "#b5651d", "border-width": 3 } },
      ],
      layout: center
        ? {
            name: "concentric",
            animate: false,
            padding: 30,
            minNodeSpacing: 28,
            levelWidth: () => 1,
            concentric: (n) => (n.id() === center ? 3 : n.data("kind") === "entity" ? 2 : 1),
          }
        : { name: "cose", animate: false, numIter: 1000, nodeRepulsion: () => 60000, idealEdgeLength: () => 110, nodeOverlap: 30, gravity: 0.2, componentSpacing: 60, padding: 30 },
    });
    // у окрестности из пары соседей «вписать в окно» даёт огромный масштаб и подписи
    if (instance.zoom() > 1.4) {
      instance.zoom(1.4);
      instance.center();
    }
    instance.on("tap", "node", (ev) => {
      const n = ev.target;
      instance.elements().addClass("faded");
      n.closedNeighborhood().removeClass("faded");
      if (n.data("kind") === "entity") setSelected(n.data("label") as string);
    });
    instance.on("dbltap", "node", (ev) => {
      const n = ev.target;
      if (n.data("kind") !== "entity") return;
      setCenter(n.id());
      setSelected(n.data("label") as string);
    });
    instance.on("tap", (ev) => {
      if (ev.target === instance) {
        instance.elements().removeClass("faded");
        setSelected(null);
      }
    });
    instance.on("mouseover", "edge", (ev) => ev.target.addClass("hover"));
    instance.on("mouseout", "edge", (ev) => ev.target.removeClass("hover"));
    return () => instance.destroy();
  }, [view.elements, center]);

  const search = () => {
    const needle = query.trim().toLowerCase();
    if (!needle) return;
    // имя или написание (синонимы свели «cost of capital» к «стоимость капитала»): сначала
    // точное совпадение, затем вхождение — у кого больше фактов
    const names = (n: (typeof entityNodes)[number]) => [n.name ?? "", ...(n.spellings ?? [])].map((x) => x.toLowerCase());
    const hits = entityNodes.filter((n) => names(n).some((x) => x.includes(needle)));
    const hit = hits.find((n) => names(n).includes(needle)) ?? [...hits].sort((a, b) => (b.facts ?? 0) - (a.facts ?? 0))[0];
    if (!hit) {
      setNote(`В ветке нет сущности, похожей на «${query.trim()}».`);
      return;
    }
    const exact = names(hit).includes(needle);
    setNote(hits.length > 1 && !exact ? `Похожих сущностей ${hits.length}; показана «${hit.name ?? hit.id}» — у неё больше всего фактов.` : "");
    setCenter(hit.id);
    setSelected(hit.name ?? hit.id);
  };

  const entities = view.elements.filter((e) => e.data.kind === "entity").length;
  const edges = view.elements.filter((e) => e.data.kind === "fact").length;
  const total = net.data?.edges.filter((e) => e.type === "факт").length ?? 0;
  const branches = (tree.data?.nodes ?? []).filter((n) => n.path === "esg" || n.path.startsWith("esg."));
  const toggle = (k: RelKey) => {
    const next = new Set(rels);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setRels(next);
  };
  const selectedId = selected ? idOf(selected) : null;

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">БАЗА ЗНАНИЙ · ГРАФ</span>
        <h1 className="page-title">Граф связей</h1>
        <p className="lead">
          Факты из статей: «ESG-фактор → связь → показатель», каждый с дословной цитатой. Щёлкните сущность — справа
          появятся все факты о ней со ссылками на статьи; двойной щелчок или поиск — её окрестность на графе.
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
          Сущностей на карте: {sizeDraft}
          <input type="range" min={20} max={200} step={10} value={sizeDraft} onChange={(e) => setSizeDraft(Number(e.target.value))} />
        </label>
        <label className="check">
          <input type="checkbox" checked={withArticles} onChange={(e) => setWithArticles(e.target.checked)} /> статьи и эксперименты
        </label>
        <form
          className="search-row"
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            search();
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
      {net.isPending && (
        <p className="muted" role="status">
          Загружаем граф с компьютера лаборатории — при первом открытии это до минуты…
        </p>
      )}
      {net.isSuccess && total === 0 && (
        <div className="card empty-state">
          <h2 className="h2">В этой ветке фактов пока нет</h2>
          <p className="muted">Граф строится моделью по статьям ветки; факты появятся по мере прохода.</p>
        </div>
      )}
      {net.isSuccess && center && (
        <p className="muted" role="status">
          Окрестность «{nameOf(center)}»: соседей {view.around}
          {view.around > NEIGHBOURS && `, показаны ${NEIGHBOURS} с самыми весомыми связями`} · двойной щелчок по соседу — его
          окрестность{" "}
          <button type="button" className="btn-ghost" onClick={() => setCenter(null)}>
            ← Вся карта
          </button>
        </p>
      )}
      {net.isSuccess && !center && total > 0 && (
        <p className="muted">
          На карте {entities} самых связанных сущностей из {view.entitiesTotal} и {edges} самых весомых связей · всего фактов в
          ветке {total}
          {view.hidden > 0 && ` · ещё ${view.hidden} связей между ними скрыто`} · найдите сущность или дважды щёлкните её —
          откроется её окрестность
        </p>
      )}
      {note && (
        <p className="muted" role="status">
          {note}
        </p>
      )}
      <div className={selected ? "graph-layout with-panel" : "graph-layout"}>
        <div ref={box} className="card graph-canvas" role="img" aria-label="Граф фактов: сущности и связи между ними" />
        {selected && (
          <FactsPanel
            name={selected}
            kb={kb}
            onClose={() => setSelected(null)}
            onFocus={selectedId && selectedId !== center ? () => setCenter(selectedId) : undefined}
          />
        )}
      </div>
    </>
  );
}
