import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { OUTCOME_LABEL, STATUS_LABEL, type ExpStatus } from "../api/experiments";
import { type Effect, H_STATUS_LABEL, type HStatus, linkType, type TargetKind } from "../api/hypotheses";
import { kbNetwork, type KbNetwork } from "../api/kb";
import { type ArticleLink, articlesSummary, type Direction, getMethodology } from "../api/methodology";
import { originalName, ruName } from "../concepts";
import { NodeSelect } from "./NodeSelect";
import { plural } from "./Ux";

// те же группы и подписи, что у стрелок на карте связей; цвет дублирует подпись
const DIRECTIONS: Array<{ key: Direction; label: string; className: string }> = [
  { key: "up", label: "повышает", className: "dir-up" },
  { key: "down", label: "снижает", className: "dir-down" },
  { key: "none", label: "не влияет", className: "dir-none" },
  { key: "other", label: "другие связи", className: "dir-other" },
];
const LABEL = Object.fromEntries(DIRECTIONS.map((d) => [d.key, d.label])) as Record<Direction, string>;

const articles = (n: number) => plural(n, "статья", "статьи", "статей");

const SUGGEST_MAX = 8;
// основы по 6 букв: окончания в русском разные (так же сравниваются повторы идей)
const stems = (text: string) => new Set((text.toLowerCase().replace(/ё/g, "е").match(/[a-zа-я0-9]{3,}/g) ?? []).map((w) => w.slice(0, 6)));

/** Понятия карты связей, все слова которых (в статье, в вариантах написания или по-русски) есть в тексте пункта. */
export function suggestConcepts(text: string, nodes: KbNetwork["nodes"]): Array<{ name: string; documents: number }> {
  const have = stems(text);
  const found = new Map<string, number>();
  for (const n of nodes) {
    if (n.kind !== "сущность" || !n.name) continue;
    for (const spelling of [n.name, ...(n.spellings ?? []), ruName(n.name)]) {
      const words = stems(spelling);
      if (words.size > 0 && [...words].every((w) => have.has(w))) {
        found.set(n.name, n.documents ?? 0);
        break;
      }
    }
  }
  return [...found]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, SUGGEST_MAX)
    .map(([name, documents]) => ({ name, documents }));
}

function Quotes({ link }: { link: ArticleLink }) {
  return (
    <li>
      «{ruName(link.from)}» — {link.relation} — «{ruName(link.to)}» <span className="muted">· {articles(link.documents)}</span>
      {link.hedged && <span className="badge st-planned">осторожная формулировка</span>}
      <ul className="list quotes">
        {link.quotes.map((q) => (
          <li key={`${q.doc_id}-${q.quote.slice(0, 20)}`}>
            <q>{q.quote}</q>{" "}
            <Link to={`/knowledge/article/${encodeURIComponent(q.doc_id)}`}>{q.title || q.doc_id}</Link>
            {q.year && <span className="muted">, {q.year}</span>}
          </li>
        ))}
      </ul>
    </li>
  );
}

function Summary({ number, factor, outcome }: { number: string; factor: string; outcome: string }) {
  const q = useQuery({
    queryKey: ["articles-summary", number, factor, outcome],
    queryFn: () => articlesSummary(number, factor, outcome),
    retry: false,
  });
  if (q.isPending) return <p className="muted">Собираем, что говорят статьи банка… Первый раз это может занять до минуты.</p>;
  if (q.isError) {
    return (
      <p className="error" role="alert">
        {q.error.message}
      </p>
    );
  }
  const s = q.data;
  const said = s.groups.filter((g) => g.key !== "other");
  return (
    <div className="articles-summary" aria-live="polite">
      <h3 className="h3">
        Как «{ruName(s.factor)}» влияет на «{ruName(s.outcome)}» — по статьям банка
      </h3>
      {s.total === 0 ? (
        <p className="muted">
          В статьях банка не нашлось утверждений, что «{ruName(s.factor)}» повышает, снижает или не меняет «{ruName(s.outcome)}». Это тоже
          ответ: связь в литературе не описана — её можно проверить расчётом.
        </p>
      ) : (
        <>
          <div className="dir-bar" role="img" aria-label={said.map((g) => `${LABEL[g.key]}: ${articles(g.documents)}`).join(", ")}>
            {said
              .filter((g) => g.documents > 0)
              .map((g) => (
                <span key={g.key} className={DIRECTIONS.find((d) => d.key === g.key)?.className} style={{ flexGrow: g.documents }} />
              ))}
          </div>
          <ul className="dir-legend">
            {said.map((g) => (
              <li key={g.key}>
                <span className={`dir-dot ${DIRECTIONS.find((d) => d.key === g.key)?.className ?? ""}`} aria-hidden="true" />
                {LABEL[g.key]}: <strong>{articles(g.documents)}</strong>
              </li>
            ))}
          </ul>
          {s.leader && s.agreement !== null && (
            <p>
              {s.agreement >= 0.75
                ? `Статьи в основном согласны: ${Math.round(s.agreement * 100)} % говорят «${LABEL[s.leader]}».`
                : `Статьи расходятся: чаще всего говорят «${LABEL[s.leader]}» — ${Math.round(s.agreement * 100)} %. Здесь особенно нужна своя проверка.`}
            </p>
          )}
          <p className="muted field-hint">
            Считаются статьи за каждой формулировкой: если одна статья пишет о связи по-разному, она войдёт в обе группы.
          </p>
        </>
      )}
      {s.groups
        .filter((g) => g.links.length > 0)
        .map((g) => (
          <details key={g.key} open={g.key !== "other"}>
            <summary>
              {g.key === "other" ? "Другие связи между этими понятиями" : `Говорят «${LABEL[g.key]}»`} · {articles(g.documents)}
            </summary>
            <ul className="list">
              {g.links.map((l) => (
                <Quotes key={`${l.from}-${l.relation}-${l.to}`} link={l} />
              ))}
            </ul>
          </details>
        ))}
      <h3 className="h3">Что по этому пункту уже есть у нас</h3>
      {s.experiments.length === 0 && s.hypotheses.length === 0 && (
        <p className="muted">Проверок и идей по этому пункту пока нет.</p>
      )}
      {s.experiments.length > 0 && (
        <ul className="list">
          {s.experiments.map((e) => (
            <li key={e.code}>
              Проверка{" "}
              <Link to={`/experiments/${e.code}`} className="mono">
                {e.code}
              </Link>{" "}
              {e.title} — {e.outcome ? OUTCOME_LABEL[e.outcome] : STATUS_LABEL[e.status as ExpStatus] ?? e.status}
            </li>
          ))}
        </ul>
      )}
      {s.hypotheses.length > 0 && (
        <ul className="list">
          {s.hypotheses.map((h) => (
            <li key={h.code}>
              Идея{" "}
              <Link to={`/hypotheses#${h.code}`} className="mono">
                {h.code}
              </Link>{" "}
              {h.title} — {H_STATUS_LABEL[h.status as HStatus] ?? h.status}
              {linkType(h.effect as Effect | "", h.target_kind as TargetKind | "") && (
                <span className="muted"> · {linkType(h.effect as Effect | "", h.target_kind as TargetKind | "")}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Вкладка «Что говорят статьи»: пункт методики → понятия → сводка фактов банка статей. */
export function ArticlesSummaryTab({ initialNode = "" }: { initialNode?: string }) {
  const [node, setNode] = useState(initialNode);
  const [factor, setFactor] = useState("");
  const [outcome, setOutcome] = useState("");
  const [asked, setAsked] = useState<{ number: string; factor: string; outcome: string } | null>(null);
  const m = useQuery({ queryKey: ["methodology"], queryFn: getMethodology });
  // та же карта связей, что на вкладке банка статей: сервер держит её в памяти, браузер — в кеше
  const concepts = useQuery({ queryKey: ["kb", "network", "esg"], queryFn: () => kbNetwork("esg"), enabled: Boolean(node) });
  const section = m.data?.sections.find((s) => s.number === node);
  const pick = (name: string) => {
    if (!factor) setFactor(name);
    else if (!outcome && name !== factor) setOutcome(name);
    else setOutcome(name);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (node && factor.trim() && outcome.trim()) setAsked({ number: node, factor: factor.trim(), outcome: outcome.trim() });
  };
  const suggested = section && concepts.data ? suggestConcepts(`${section.title} ${section.content}`, concepts.data.nodes) : [];
  return (
    <section className="card" role="tabpanel">
      <h2 className="h2">Что говорят статьи</h2>
      <p className="muted">
        Сводка по всем статьям банка: сколько статей говорят, что фактор повышает результат, снижает его или не влияет, и
        насколько они согласны. За каждой цифрой — цитаты. Так видно, где методика опирается на согласие статей, а где
        статьи спорят и нужна своя проверка.
      </p>
      <form className="articles-form" onSubmit={submit}>
        <label className="field" htmlFor="as-node">
          Пункт методики
          <NodeSelect
            id="as-node"
            value={node}
            onChange={(v) => {
              setNode(v);
              setFactor("");
              setOutcome("");
              setAsked(null);
            }}
            emptyLabel="— выберите пункт —"
          />
        </label>
        {node && (
          <div className="field">
            <span>Понятия, о которых говорит пункт</span>
            {concepts.isPending && <span className="muted">Ищем в банке статей…</span>}
            {concepts.isError && (
              <span className="error" role="alert">
                {concepts.error.message}
              </span>
            )}
            {concepts.isSuccess && suggested.length === 0 && (
              <span className="muted">Подходящих понятий не нашлось — впишите их сами.</span>
            )}
            {suggested.length > 0 && (
              <div className="chips-row">
                {suggested.map((c) => (
                  <button key={c.name} type="button" className="chip" onClick={() => pick(c.name)} title={originalName(c.name) || undefined}>
                    {ruName(c.name)} · {articles(c.documents)}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <fieldset className="field-row">
          <legend>Связь, о которой спрашиваем</legend>
          <label className="field">
            Фактор — что влияет
            <input value={factor} onChange={(e) => setFactor(e.target.value)} placeholder="например, ESG-рейтинг" />
          </label>
          <label className="field">
            Результат — на что влияет
            <input value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="например, стоимость долга" />
          </label>
          <p className="muted field-hint">
            Нажмите на понятие выше — оно встанет в пустое поле так, как записано в статьях (часто по-английски). Синонимы банк
            статей сводит сам.
          </p>
        </fieldset>
        <div className="review-form">
          <button type="submit" className="btn-primary" disabled={!node || !factor.trim() || !outcome.trim()}>
            Показать, что говорят статьи
          </button>
        </div>
      </form>
      {asked && <Summary {...asked} />}
    </section>
  );
}
