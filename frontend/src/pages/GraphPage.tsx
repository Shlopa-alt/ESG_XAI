import { useQuery } from "@tanstack/react-query";
import cytoscape, { type ElementDefinition } from "cytoscape";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { type KbNetwork, kbNetwork, kbTree } from "../api/kb";
import { BankTabs } from "../components/SectionTabs";
import { plural } from "../components/Ux";
import { conceptKey, originalName, POPULAR, ruName } from "../concepts";

// Цвет связи — её смысл; подпись дублирует цвет, поэтому он не единственный носитель смысла
const REL_GROUPS = [
  { key: "up", label: "повышает", color: "#1baf7a", match: (r: string) => r.includes("повыша") && !r.includes("не ") },
  { key: "down", label: "снижает", color: "#eb6834", match: (r: string) => r.includes("снижа") && !r.includes("не ") },
  { key: "none", label: "не влияет", color: "#8a948e", match: (r: string) => r.includes("не влияет") },
  { key: "other", label: "другие связи", color: "#2a78d6", match: () => true },
] as const;
type RelKey = (typeof REL_GROUPS)[number]["key"];
const groupOf = (rel: string): (typeof REL_GROUPS)[number] => REL_GROUPS.find((g) => g.match(rel)) ?? REL_GROUPS[3];

const SIDE_ROWS = 6; // сколько связей с каждой стороны видно в панели сразу
const NEIGHBOURS = 11; // сколько соседей с каждой стороны рисовать на графе: больше подписи не читаются
type Fact = KbNetwork["edges"][number];
type Concept = KbNetwork["nodes"][number];

interface DatasetFact {
  about: string;
  direction: string;
  relation: string;
  other: string;
  quotes: Array<{ quote: string; doc_id: string; title: string; year: number | null; url: string | null }>;
}

async function kbDataset(name: string, kb: string): Promise<{ name: string; facts: DatasetFact[] }> {
  const res = await fetch(`/api/kb/dataset?${new URLSearchParams({ name, kb }).toString()}`, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`Банк статей: ошибка ${res.status}`);
  return (await res.json()) as { name: string; facts: DatasetFact[] };
}

const label = (c: Concept | undefined) => ruName(c?.name ?? c?.id ?? "");
const keyName = (c: Concept) => c.name ?? c.id;

/** Одна связь с соседним понятием: самая весомая формулировка и сколько статей о ней говорят. */
interface Link2 {
  other: Concept;
  relation: string;
  group: RelKey;
  articles: number;
  top: number; // вес этой формулировки
}

function sideLinks(facts: Fact[], byId: Map<string, Concept>, pick: (e: Fact) => string | null): Link2[] {
  const best = new Map<string, Link2>();
  for (const e of facts) {
    const id = pick(e);
    const other = id ? byId.get(id) : undefined;
    if (!other) continue;
    const weight = e.weight ?? 1;
    const was = best.get(other.id);
    const articles = (was?.articles ?? 0) + weight;
    if (!was || weight > was.top) {
      best.set(other.id, { other, relation: e.label ?? "", group: groupOf(e.label ?? "").key, articles, top: weight });
    } else {
      was.articles = articles;
    }
  }
  // почти у всех связей по одной статье: при равенстве выше понятие, о котором пишут чаще
  return [...best.values()].sort((a, b) => b.articles - a.articles || (b.other.facts ?? 0) - (a.other.facts ?? 0));
}

/** Цитаты по одной связи: каждая связь держится на дословной цитате из статьи. */
function Quotes({ name, otherName, kb, onOpen, onClose }: { name: string; otherName: string; kb: string; onOpen: () => void; onClose: () => void }) {
  const q = useQuery({ queryKey: ["kb", "dataset", kb, name], queryFn: () => kbDataset(name, kb) });
  const facts = (q.data?.facts ?? []).filter((f) => f.other === otherName);
  return (
    <section className="card concept-quotes" aria-label="Что говорят статьи">
      <div className="viz-head">
        <div>
          <span className="eyebrow">ЧТО ГОВОРЯТ СТАТЬИ</span>
          <h2 className="h3">
            {ruName(name)} и {ruName(otherName)}
          </h2>
        </div>
        <div className="actions">
          <button type="button" className="btn-ghost" onClick={onOpen}>
            Открыть «{ruName(otherName)}»
          </button>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
      <p className="muted">Цитаты приведены на языке статьи. Нажмите на название, чтобы прочитать статью целиком.</p>
      {q.isPending && <p className="muted">Загрузка цитат…</p>}
      {q.isError && (
        <p className="error" role="alert">
          {q.error.message}
        </p>
      )}
      {q.isSuccess && facts.length === 0 && <p className="muted">Цитаты по этой связи не найдены: возможно, она из другой темы.</p>}
      <ul className="facts">
        {facts.map((f, i) => {
          const g = groupOf(f.relation);
          const [from, to] = f.direction === "←" ? [f.other, f.about] : [f.about, f.other];
          return (
            <li key={i}>
              <div className="fact-line">
                <strong>{ruName(from)}</strong>{" "}
                <span className="rel-tag" style={{ borderColor: g.color }}>
                  {f.relation}
                </span>{" "}
                <strong>{ruName(to)}</strong>
              </div>
              {f.quotes.slice(0, 3).map((qt) => (
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
    </section>
  );
}

function Side({
  title,
  empty,
  links,
  arrow,
  active,
  onConcept,
  onQuotes,
}: {
  title: string;
  empty: string;
  links: Link2[];
  arrow: "in" | "out";
  active: string | null;
  onConcept: (id: string) => void;
  onQuotes: (id: string) => void;
}) {
  const [rows, setRows] = useState(SIDE_ROWS);
  const first = links[0]?.other.id;
  useEffect(() => setRows(SIDE_ROWS), [first]); // другое понятие — снова короткий список
  const shown = links.slice(0, rows);
  return (
    <div className={`concept-side concept-${arrow}`}>
      <h3 className="concept-side-title">{title}</h3>
      {links.length === 0 && <p className="muted">{empty}</p>}
      <ul className="concept-rows">
        {shown.map((l) => {
          const g = REL_GROUPS.find((x) => x.key === l.group) ?? REL_GROUPS[3];
          return (
            <li key={l.other.id} className={active === l.other.id ? "concept-row active" : "concept-row"} style={{ borderColor: g.color }}>
              <button type="button" className="concept-open" title="Открыть это понятие" onClick={() => onConcept(l.other.id)}>
                <span className="concept-name">{label(l.other)}</span>
                {originalName(keyName(l.other)) && <span className="concept-orig">{originalName(keyName(l.other))}</span>}
              </button>
              <button type="button" className="concept-evidence" onClick={() => onQuotes(l.other.id)}>
                <span className="concept-rel">{l.relation}</span>
                <span className="concept-count">{plural(l.articles, "статья", "статьи", "статей")}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {links.length > SIDE_ROWS && (
        <div className="concept-more">
          {rows < links.length && (
            <button type="button" className="link-btn" onClick={() => setRows(rows + 20)}>
              Показать ещё {Math.min(20, links.length - rows)} из {links.length - rows}
            </button>
          )}
          {rows > SIDE_ROWS && (
            <button type="button" className="link-btn" onClick={() => setRows(SIDE_ROWS)}>
              Свернуть
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Что нарисовать: вся карта или понятие в центре со связями по сторонам. */
function overviewElements(facts: Fact[], nodes: Concept[], size: number): ElementDefinition[] {
  const degree = new Map<string, number>();
  for (const e of facts) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + (e.weight ?? 1));
    degree.set(e.target, (degree.get(e.target) ?? 0) + (e.weight ?? 1));
  }
  const keep = new Set([...degree].sort((a, b) => b[1] - a[1]).slice(0, size).map(([id]) => id));
  const pairs = new Map<string, Fact>();
  for (const e of facts) {
    if (!keep.has(e.source) || !keep.has(e.target) || e.source === e.target) continue;
    const k = e.source < e.target ? `${e.source}|${e.target}` : `${e.target}|${e.source}`;
    const was = pairs.get(k);
    if (!was || (e.weight ?? 1) > (was.weight ?? 1)) pairs.set(k, e);
  }
  const drawn = [...pairs.values()].sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1)).slice(0, size * 2);
  const linked = new Set(drawn.flatMap((e) => [e.source, e.target]));
  const out: ElementDefinition[] = [];
  for (const n of nodes) {
    if (linked.has(n.id)) {
      out.push({ data: { id: n.id, label: label(n), size: Math.min(58, 18 + 4 * Math.log2(Math.max(1, n.facts ?? 1))) } });
    }
  }
  for (const e of drawn) {
    out.push({
      data: {
        id: `${e.source}>${e.target}>${e.label}`,
        source: e.source,
        target: e.target,
        label: e.label ?? "",
        color: groupOf(e.label ?? "").color,
        width: Math.min(6, 1.5 + 1.5 * Math.log2(Math.max(1, e.weight ?? 1))),
      },
    });
  }
  return out;
}

function focusElements(concept: Concept, incoming: Link2[], outgoing: Link2[]): ElementDefinition[] {
  const left = incoming.slice(0, NEIGHBOURS);
  const taken = new Set(left.map((l) => l.other.id));
  const right = outgoing.filter((l) => !taken.has(l.other.id)).slice(0, NEIGHBOURS);
  const out: ElementDefinition[] = [
    { data: { id: concept.id, label: label(concept), size: 76, place: "center" }, position: { x: 0, y: 0 } },
  ];
  const side = (links: Link2[], dir: -1 | 1) => {
    links.forEach((l, i) => {
      const t = links.length > 1 ? (i / (links.length - 1)) * 2 - 1 : 0; // −1…1 сверху вниз
      const color = (REL_GROUPS.find((g) => g.key === l.group) ?? REL_GROUPS[3]).color;
      out.push({
        data: { id: l.other.id, label: label(l.other), size: 20 + Math.min(16, 2.5 * Math.log2(Math.max(1, l.other.facts ?? 1))), place: dir < 0 ? "left" : "right" },
        // дуга: крайние ближе к центру — стрелки и подписи не пересекаются
        position: { x: dir * (300 - 70 * t * t), y: t * Math.max(70, (links.length - 1) * 31) },
      });
      out.push({
        data: {
          id: `${dir < 0 ? l.other.id : concept.id}>${dir < 0 ? concept.id : l.other.id}`,
          source: dir < 0 ? l.other.id : concept.id,
          target: dir < 0 ? concept.id : l.other.id,
          other: l.other.id,
          label: l.relation,
          color,
          width: Math.min(6, 2 + 1.5 * Math.log2(Math.max(1, l.articles))),
        },
      });
    });
  };
  side(left, -1);
  side(right, 1);
  return out;
}

/** Холст графа: нажатие на понятие выводит его в центр, на связь — открывает цитаты. */
function GraphCanvas({ elements, focused, onNode, onEdge }: { elements: ElementDefinition[]; focused: boolean; onNode: (id: string) => void; onEdge: (other: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<cytoscape.Core | null>(null);
  useEffect(() => {
    if (!box.current) return undefined;
    const instance = cytoscape({
      container: box.current,
      elements,
      minZoom: 0.2,
      maxZoom: 3,
      wheelSensitivity: 0.25,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#2a4a3a",
            label: "data(label)",
            width: "data(size)",
            height: "data(size)",
            // раскладка общей карты оставляет место под подписи такого размера, затем они приводятся к экрану
            "font-size": focused ? 13 : 22,
            "font-family": "IBM Plex Sans, sans-serif",
            color: "#17201b",
            "text-valign": "bottom",
            "text-margin-y": 4,
            "text-wrap": "wrap",
            "text-max-width": "170px",
            "text-outline-color": "#ffffff",
            "text-outline-width": 2.5,
            "border-width": 2,
            "border-color": "#ffffff",
          },
        },
        { selector: 'node[place = "center"]', style: { "background-color": "#b5651d", "font-weight": "bold", "text-margin-y": 6, "text-background-color": "#ffffff", "text-background-opacity": 1, "text-background-padding": "3px", "text-background-shape": "roundrectangle" } },
        { selector: 'node[place = "left"]', style: { "text-halign": "left", "text-valign": "center", "text-margin-x": -8, "text-margin-y": 0, "text-max-width": "190px" } },
        { selector: 'node[place = "right"]', style: { "text-halign": "right", "text-valign": "center", "text-margin-x": 8, "text-margin-y": 0, "text-max-width": "190px" } },
        {
          selector: "edge",
          style: { width: "data(width)", "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": "triangle", "curve-style": "straight", "arrow-scale": 1, opacity: focused ? 0.85 : 0.45 },
        },
        { selector: "node.hot", style: { "border-color": "#b5651d", "border-width": 4 } },
        { selector: ".faded", style: { opacity: 0.12 } },
        { selector: "edge.near", style: { opacity: 1 } },
        {
          selector: "edge.tell",
          style: { label: "data(label)", "font-size": 12, "font-family": "IBM Plex Sans, sans-serif", color: "#17201b", "text-background-color": "#ffffff", "text-background-opacity": 1, "text-background-padding": "3px", "text-border-color": "#dde3df", "text-border-width": 1, "text-border-opacity": 1, opacity: 1, "z-index": 10 },
        },
      ],
      layout: focused
        ? { name: "preset", fit: true, padding: 24 }
        : { name: "cose", animate: false, nodeDimensionsIncludeLabels: true, numIter: 1500, nodeRepulsion: () => 120000, idealEdgeLength: () => 170, nodeOverlap: 60, gravity: 0.3, componentSpacing: 70, padding: 20 },
    });
    cy.current = instance;
    if (instance.zoom() > 1.25) {
      instance.zoom(1.25);
      instance.center();
    }
    // подписи одного размера на экране: при большом графе масштаб мелкий, а читать всё равно надо
    const readable = () => {
      const k = Math.min(3, 1 / instance.zoom());
      instance.nodes().style({ "font-size": 13 * k, "text-max-width": `${(focused ? 190 : 150) * k}px` });
    };
    readable();
    if (focused) {
      // подписи сбоку от кругов: вписываем вместе с ними, иначе длинные обрежутся по краю холста
      instance.fit(undefined, 16);
      readable();
      instance.fit(undefined, 16);
      if (instance.zoom() > 1.25) {
        instance.zoom(1.25);
        instance.center();
      }
      readable();
    }
    instance.on("zoom", readable);
    instance.on("mouseover", "node", (ev) => {
      if (box.current) box.current.style.cursor = "pointer";
      const near = ev.target.closedNeighborhood();
      if (!focused) {
        instance.elements().addClass("faded");
        near.removeClass("faded");
        near.edges().addClass("near");
      }
      ev.target.addClass("hot");
      near.edges().addClass("tell");
    });
    instance.on("mouseout", "node", (ev) => {
      if (box.current) box.current.style.cursor = "";
      instance.elements().removeClass("faded near tell");
      ev.target.removeClass("hot");
    });
    instance.on("mouseover", "edge", (ev) => ev.target.addClass("tell"));
    instance.on("mouseout", "edge", (ev) => ev.target.removeClass("tell"));
    instance.on("tap", "node", (ev) => onNode(ev.target.id() as string));
    instance.on("tap", "edge", (ev) => {
      const other = ev.target.data("other") as string | undefined;
      if (other) onEdge(other);
    });
    return () => {
      cy.current = null;
      instance.destroy();
    };
  }, [elements, focused, onNode, onEdge]);
  const zoom = (k: number) => {
    const c = cy.current;
    if (c) c.zoom({ level: c.zoom() * k, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } });
  };
  return (
    <div className="card graph-stage">
      <div ref={box} className="graph-canvas" role="img" aria-label={focused ? "Граф: выбранное понятие в центре, слева что на него влияет, справа на что влияет оно" : "Граф: самые связанные понятия банка статей"} />
      <div className="graph-zoom" role="group" aria-label="Масштаб графа">
        <button type="button" className="btn-ghost" aria-label="Крупнее" onClick={() => zoom(1.25)}>
          +
        </button>
        <button type="button" className="btn-ghost" aria-label="Мельче" onClick={() => zoom(0.8)}>
          −
        </button>
        <button type="button" className="btn-ghost" onClick={() => cy.current?.fit(undefined, 24)}>
          Вписать
        </button>
      </div>
    </div>
  );
}

export function Graph() {
  const [kb, setKb] = useState("esg");
  const [rels, setRels] = useState<Set<RelKey>>(new Set(["up", "down", "none", "other"]));
  const [size, setSize] = useState(30);
  const [current, setCurrent] = useState<string | null>(null); // null — вся карта
  const [trail, setTrail] = useState<string[]>([]); // откуда пришли: можно вернуться назад
  const [evidence, setEvidence] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Concept[] | null>(null);
  const tree = useQuery({ queryKey: ["kb", "kbs"], queryFn: () => kbTree("esg") });
  const net = useQuery({ queryKey: ["kb", "network", kb], queryFn: () => kbNetwork(kb) });

  const nodes = useMemo(() => (net.data?.nodes ?? []).filter((n) => n.kind === "сущность"), [net.data]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const facts = useMemo(() => (net.data?.edges ?? []).filter((e) => e.type === "факт"), [net.data]);
  const shownFacts = useMemo(() => facts.filter((e) => rels.has(groupOf(e.label ?? "").key)), [facts, rels]);
  const popular = useMemo(() => {
    const byKey = new Map(nodes.map((n) => [conceptKey(keyName(n)), n]));
    const curated = POPULAR.flatMap((k) => byKey.get(k) ?? []);
    return curated.length >= 4 ? curated : [...nodes].sort((a, b) => (b.facts ?? 0) - (a.facts ?? 0)).slice(0, 10);
  }, [nodes]);

  useEffect(() => {
    setCurrent(null);
    setTrail([]);
    setEvidence(null);
    setFound(null);
  }, [kb]);

  const open = useCallback((id: string) => {
    setFound(null);
    setEvidence(null);
    setCurrent((was) => {
      if (was === id) return was;
      if (was) setTrail((t) => [...t, was]);
      return id;
    });
  }, []);
  const back = () => {
    const last = trail[trail.length - 1];
    if (!last) return;
    setTrail(trail.slice(0, -1));
    setEvidence(null);
    setCurrent(last);
  };
  const toMap = () => {
    setCurrent(null);
    setTrail([]);
    setEvidence(null);
  };
  const search = (e: FormEvent) => {
    e.preventDefault();
    const needle = query.trim().toLowerCase();
    if (!needle) return;
    const names = (n: Concept) => [keyName(n), label(n), ...(n.spellings ?? [])].map((x) => x.toLowerCase());
    const hits = nodes.filter((n) => names(n).some((x) => x.includes(needle))).sort((a, b) => (b.facts ?? 0) - (a.facts ?? 0));
    const exact = hits.find((n) => names(n).includes(needle));
    if (exact) {
      open(exact.id);
      return;
    }
    if (hits.length === 1 && hits[0]) {
      open(hits[0].id);
      return;
    }
    setFound(hits.slice(0, 12));
  };
  const concept = current ? byId.get(current) : undefined;
  const incoming = useMemo(() => sideLinks(shownFacts, byId, (e) => (e.target === current && e.source !== current ? e.source : null)), [shownFacts, byId, current]);
  const outgoing = useMemo(() => sideLinks(shownFacts, byId, (e) => (e.source === current && e.target !== current ? e.target : null)), [shownFacts, byId, current]);
  const elements = useMemo(
    () => (concept ? focusElements(concept, incoming, outgoing) : overviewElements(shownFacts, nodes, size)),
    [concept, incoming, outgoing, shownFacts, nodes, size],
  );
  const evidenceNode = evidence ? byId.get(evidence) : undefined;
  const branches = (tree.data?.nodes ?? []).filter((n) => n.path === "esg" || n.path.startsWith("esg."));
  const toggle = (k: RelKey) => {
    const next = new Set(rels);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setRels(next);
  };
  const previous = trail.length ? byId.get(trail[trail.length - 1] ?? "") : undefined;
  const hiddenIn = Math.max(0, incoming.length - NEIGHBOURS);
  const hiddenOut = Math.max(0, outgoing.length - NEIGHBOURS);

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">БАНК СТАТЕЙ</span>
        <h1 className="page-title">Карта связей</h1>
        <p className="lead">
          Граф того, что говорят статьи: круги — понятия, стрелки — утверждения вида «одно влияет на другое», и каждое
          подтверждено цитатой. Нажмите на понятие, чтобы вывести его в центр.
        </p>
      </section>
      <BankTabs />
      <div className="card graph-controls">
        <form className="search-row" role="search" onSubmit={search}>
          <label htmlFor="graph-q" className="sr-only">
            Найти понятие на графе
          </label>
          <input id="graph-q" className="search" placeholder="Найти понятие: прибыльность, ESG-рейтинг, cost of capital…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button type="submit" className="btn-primary">
            Найти
          </button>
        </form>
        <label className="field inline">
          Тема
          <select value={kb} onChange={(e) => setKb(e.target.value)}>
            {branches.map((b) => (
              <option key={b.path} value={b.path}>
                {"  ".repeat(b.depth)}
                {b.title}
              </option>
            ))}
          </select>
        </label>
        {!concept && (
          <label className="field inline">
            Понятий на графе: {size}
            <input type="range" min={15} max={100} step={5} value={size} onChange={(e) => setSize(Number(e.target.value))} />
          </label>
        )}
        {net.isSuccess && facts.length > 0 && (
          <div className="rel-legend" role="group" aria-label="Какие связи показывать">
            {REL_GROUPS.map((g) => (
              <button key={g.key} type="button" aria-pressed={rels.has(g.key)} className={rels.has(g.key) ? "chip active-rel" : "chip"} onClick={() => toggle(g.key)}>
                <span className="rel-swatch" style={{ background: g.color }} aria-hidden="true" />
                {g.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {net.isError && (
        <p className="error" role="alert">
          {net.error.message}
        </p>
      )}
      {net.isPending && (
        <p className="muted" role="status">
          Загружаем граф с компьютера лаборатории. При первом открытии это может занять до минуты…
        </p>
      )}
      {net.isSuccess && facts.length === 0 && (
        <div className="card empty-state">
          <h2 className="h2">В этой теме связей пока нет</h2>
          <p className="muted">ИИ-помощник выписывает их из статей темы, и они появятся по мере обработки. Попробуйте выбрать «Все».</p>
        </div>
      )}
      {found && (
        <section className="card concept-found" aria-label="Результаты поиска">
          {found.length === 0 ? (
            <p>Такого понятия нет. Попробуйте другое слово или английское название: большинство статей написаны на английском.</p>
          ) : (
            <>
              <p>Похожие понятия: выберите нужное.</p>
              <div className="chips-row">
                {found.map((n) => (
                  <button key={n.id} type="button" className="chip" onClick={() => open(n.id)}>
                    {label(n)}
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      )}
      {net.isSuccess && facts.length > 0 && (
        <>
          {concept && (
            <div className="graph-bar">
              {previous && (
                <button type="button" className="btn-ghost" onClick={back}>
                  ← Назад: {label(previous)}
                </button>
              )}
              <button type="button" className="btn-ghost" onClick={toMap}>
                Вся карта
              </button>
            </div>
          )}
          <div className="graph-layout with-panel">
            <GraphCanvas elements={elements} focused={Boolean(concept)} onNode={open} onEdge={setEvidence} />
            <aside className="graph-panel" aria-label={concept ? `Понятие: ${label(concept)}` : "Как читать граф"}>
              {concept ? (
                <>
                  <div className="concept-center">
                    <span className="eyebrow">ПОНЯТИЕ</span>
                    <h2 className="concept-title">{label(concept)}</h2>
                    {originalName(keyName(concept)) && <span className="concept-orig">{originalName(keyName(concept))}</span>}
                    <p className="muted">Упоминается в {plural(concept.facts ?? 0, "утверждении", "утверждениях", "утверждениях")} из статей.</p>
                  </div>
                  {evidenceNode ? (
                    <Quotes name={keyName(concept)} otherName={keyName(evidenceNode)} kb={kb} onOpen={() => open(evidenceNode.id)} onClose={() => setEvidence(null)} />
                  ) : (
                    <>
                      {(hiddenIn > 0 || hiddenOut > 0) && <p className="muted">На графе самые весомые связи, остальные в списках ниже.</p>}
                      <Side title="Что на это влияет" empty="В статьях таких связей не нашлось." links={incoming} arrow="in" active={evidence} onConcept={open} onQuotes={setEvidence} />
                      <Side title="На что это влияет" empty="В статьях таких связей не нашлось." links={outgoing} arrow="out" active={evidence} onConcept={open} onQuotes={setEvidence} />
                    </>
                  )}
                </>
              ) : (
                <div className="card graph-help">
                  <h2 className="h3">Как читать граф</h2>
                  <ul className="list">
                    <li>Чем больше круг, тем чаще о понятии пишут.</li>
                    <li>Цвет стрелки показывает связь: повышает, снижает, не влияет.</li>
                    <li>Наведите на круг, чтобы выделить его связи.</li>
                    <li>Нажмите на круг, чтобы вывести понятие в центр и прочитать цитаты.</li>
                  </ul>
                  <h3 className="h3">С чего начать</h3>
                  <div className="chips-row">
                    {popular.map((n) => (
                      <button key={n.id} type="button" className="chip" onClick={() => open(n.id)}>
                        {label(n)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </aside>
          </div>
        </>
      )}
    </>
  );
}
