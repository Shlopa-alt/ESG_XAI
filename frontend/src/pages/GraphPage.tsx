import { useQuery } from "@tanstack/react-query";
import cytoscape, { type ElementDefinition } from "cytoscape";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
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

const SIDE_ROWS = 8; // сколько связей с каждой стороны видно сразу
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

/** Общая карта: самые связанные понятия одной картинкой, нажатие открывает понятие. */
function Overview({ facts, nodes, size, onOpen }: { facts: Fact[]; nodes: Concept[]; size: number; onOpen: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const elements = useMemo(() => {
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
        out.push({ data: { id: n.id, label: label(n), size: Math.min(50, 16 + 4 * Math.log2(Math.max(1, n.facts ?? 1))) } });
      }
    }
    for (const e of drawn) {
      out.push({
        data: {
          id: `${e.source}>${e.target}>${e.label}`,
          source: e.source,
          target: e.target,
          color: groupOf(e.label ?? "").color,
          width: Math.min(6, 1 + 1.5 * Math.log2(Math.max(1, e.weight ?? 1))),
        },
      });
    }
    return out;
  }, [facts, nodes, size]);
  useEffect(() => {
    if (!box.current) return undefined;
    const instance = cytoscape({
      container: box.current,
      elements,
      minZoom: 0.3,
      maxZoom: 2.5,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#2a4a3a",
            label: "data(label)",
            width: "data(size)",
            height: "data(size)",
            "font-size": 13,
            color: "#17201b",
            "text-valign": "bottom",
            "text-margin-y": 4,
            "text-wrap": "wrap",
            "text-max-width": "150px",
            "text-outline-color": "#ffffff",
            "text-outline-width": 2,
          },
        },
        { selector: "edge", style: { width: "data(width)", "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.7, opacity: 0.45 } },
        { selector: ".faded", style: { opacity: 0.12 } },
        { selector: "edge.near", style: { opacity: 1 } },
      ],
      layout: { name: "cose", animate: false, nodeDimensionsIncludeLabels: true, numIter: 1200, nodeRepulsion: () => 90000, idealEdgeLength: () => 140, nodeOverlap: 40, gravity: 0.25, componentSpacing: 80, padding: 40 },
    });
    instance.on("mouseover", "node", (ev) => {
      instance.elements().addClass("faded");
      const near = ev.target.closedNeighborhood();
      near.removeClass("faded");
      near.edges().addClass("near");
    });
    instance.on("mouseout", "node", () => {
      instance.elements().removeClass("faded");
      instance.edges().removeClass("near");
    });
    instance.on("tap", "node", (ev) => onOpen(ev.target.id() as string));
    return () => instance.destroy();
  }, [elements, onOpen]);
  return <div ref={box} className="card graph-canvas" role="img" aria-label="Общая карта: самые связанные понятия банка статей" />;
}

type Mode = "concept" | "map";

export function Graph() {
  const [kb, setKb] = useState("esg");
  const [mode, setMode] = useState<Mode>("concept");
  const [rels, setRels] = useState<Set<RelKey>>(new Set(["up", "down", "none", "other"]));
  const [size, setSize] = useState(30);
  const [current, setCurrent] = useState<string | null>(null);
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
  useEffect(() => {
    if (current === null && popular[0]) setCurrent(popular[0].id);
  }, [current, popular]);

  const open = (id: string) => {
    setMode("concept");
    setFound(null);
    setEvidence(null);
    setTrail((t) => (current && current !== id ? [...t, current] : t));
    setCurrent(id);
  };
  const back = () => {
    const last = trail[trail.length - 1];
    if (!last) return;
    setTrail(trail.slice(0, -1));
    setEvidence(null);
    setCurrent(last);
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
  const evidenceNode = evidence ? byId.get(evidence) : undefined;
  const branches = (tree.data?.nodes ?? []).filter((n) => n.path === "esg" || n.path.startsWith("esg."));
  const toggle = (k: RelKey) => {
    const next = new Set(rels);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setRels(next);
  };
  const previous = trail.length ? byId.get(trail[trail.length - 1] ?? "") : undefined;

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">БАНК СТАТЕЙ</span>
        <h1 className="page-title">Карта связей</h1>
        <p className="lead">
          Из статей выписаны утверждения вида «одно влияет на другое», и каждое подтверждено цитатой. Выберите понятие и
          посмотрите, что на него влияет и на что влияет оно.
        </p>
      </section>
      <BankTabs />
      <div className="card graph-controls">
        <form className="search-row" role="search" onSubmit={search}>
          <label htmlFor="graph-q" className="sr-only">
            Найти понятие на карте
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
        <div className="filters" role="group" aria-label="Вид карты">
          <button type="button" className={mode === "concept" ? "chip active" : "chip"} aria-pressed={mode === "concept"} onClick={() => setMode("concept")}>
            По понятиям
          </button>
          <button type="button" className={mode === "map" ? "chip active" : "chip"} aria-pressed={mode === "map"} onClick={() => setMode("map")}>
            Общая карта
          </button>
        </div>
      </div>
      {net.isError && (
        <p className="error" role="alert">
          {net.error.message}
        </p>
      )}
      {net.isPending && (
        <p className="muted" role="status">
          Загружаем карту с компьютера лаборатории. При первом открытии это может занять до минуты…
        </p>
      )}
      {net.isSuccess && facts.length === 0 && (
        <div className="card empty-state">
          <h2 className="h2">В этой теме связей пока нет</h2>
          <p className="muted">ИИ-помощник выписывает их из статей темы, и они появятся по мере обработки. Попробуйте выбрать «Все темы».</p>
        </div>
      )}
      {found && (
        <section className="card concept-found" aria-label="Результаты поиска">
          {found.length === 0 ? (
            <p>
              Такого понятия нет. Попробуйте другое слово или английское название, ведь большинство статей написаны на английском.
            </p>
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
        <div className="rel-legend" role="group" aria-label="Какие связи показывать">
          {REL_GROUPS.map((g) => (
            <button key={g.key} type="button" aria-pressed={rels.has(g.key)} className={rels.has(g.key) ? "chip active-rel" : "chip"} onClick={() => toggle(g.key)}>
              <span className="rel-swatch" style={{ background: g.color }} aria-hidden="true" />
              {g.label}
            </button>
          ))}
        </div>
      )}
      {net.isSuccess && facts.length > 0 && mode === "concept" && (
        <>
          <div className="concept-popular">
            <span className="muted">С чего начать:</span>
            <div className="chips-row">
              {popular.map((n) => (
                <button key={n.id} type="button" className={n.id === current ? "chip active" : "chip"} aria-pressed={n.id === current} onClick={() => open(n.id)}>
                  {label(n)}
                </button>
              ))}
            </div>
          </div>
          {previous && (
            <button type="button" className="btn-ghost concept-back" onClick={back}>
              ← Назад: {label(previous)}
            </button>
          )}
          {concept && (
            <div className="concept-map">
              <Side title="Что на это влияет" empty="В статьях таких связей не нашлось." links={incoming} arrow="in" active={evidence} onConcept={open} onQuotes={setEvidence} />
              <div className="concept-center">
                <span className="eyebrow">ПОНЯТИЕ</span>
                <h2 className="concept-title">{label(concept)}</h2>
                {originalName(keyName(concept)) && <span className="concept-orig">{originalName(keyName(concept))}</span>}
                <p className="muted">
                  Упоминается в {plural(concept.facts ?? 0, "утверждении", "утверждениях", "утверждениях")} из статей. Нажмите на
                  соседнее понятие, чтобы перейти к нему, или на число статей, чтобы увидеть цитаты.
                </p>
              </div>
              <Side title="На что это влияет" empty="В статьях таких связей не нашлось." links={outgoing} arrow="out" active={evidence} onConcept={open} onQuotes={setEvidence} />
            </div>
          )}
          {concept && evidenceNode && (
            <Quotes name={keyName(concept)} otherName={keyName(evidenceNode)} kb={kb} onOpen={() => open(evidenceNode.id)} onClose={() => setEvidence(null)} />
          )}
        </>
      )}
      {net.isSuccess && facts.length > 0 && mode === "map" && (
        <>
          <div className="map-size">
            <label className="field inline">
              Понятий на карте: {size}
              <input type="range" min={15} max={80} step={5} value={size} onChange={(e) => setSize(Number(e.target.value))} />
            </label>
            <p className="muted">Самые связанные понятия: чем больше круг, тем чаще о понятии пишут. Наведите, чтобы выделить связи, и нажмите, чтобы открыть.</p>
          </div>
          <Overview facts={shownFacts} nodes={nodes} size={size} onOpen={open} />
        </>
      )}
    </>
  );
}
