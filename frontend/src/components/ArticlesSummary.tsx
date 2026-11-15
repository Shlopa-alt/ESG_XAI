import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { OUTCOME_LABEL, STATUS_LABEL, type ExpStatus } from "../api/experiments";
import { type Effect, H_STATUS_LABEL, type HStatus, linkType, type TargetKind } from "../api/hypotheses";
import { kbNetwork, type KbNetwork } from "../api/kb";
import {
  addCrBasis,
  addCrKbBasis,
  type ArticleLink,
  articlesSummary,
  type ArticlesSummary,
  createCr,
  type Direction,
  type Finding,
  getMethodology,
  type Section,
} from "../api/methodology";
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

const pct = (x: number) => `${Math.round(x * 100)} %`;

/** Подсказка, что сводка значит для пункта: что сделать дальше. Решает человек. */
function FindingText({ f, s }: { f: Finding; s: ArticlesSummary }) {
  const exp = (code: string) => (
    <Link to={`/experiments/${code}`} className="mono">
      {code}
    </Link>
  );
  const idea = (code: string) => (
    <Link to={`/hypotheses#${code}`} className="mono">
      {code}
    </Link>
  );
  switch (f.kind) {
    case "silent":
      return <>Статьи о такой связи молчат. Её можно проверить расчётом — это будет новое знание, а не повтор.</>;
    case "few":
      return <>О связи пишут всего {articles(f.documents)} — согласие или спор по ним не видны. Выводы делать рано.</>;
    case "consensus":
      return (
        <>
          Статьи в основном согласны: {pct(f.agreement)} говорят «{LABEL[f.leader]}». Если в пункте этого нет — стоит закрепить
          это в методике, опираясь на цитаты ниже.
        </>
      );
    case "disputed":
      return (
        <>
          Статьи расходятся: чаще всего говорят «{LABEL[f.leader]}», но только {pct(f.agreement)}. Здесь особенно нужна своя
          проверка на наших данных.
        </>
      );
    case "idea_against":
      return (
        <>
          Идея {idea(f.code)} говорит «{LABEL[f.claims]}», а статьи в основном — «{LABEL[s.leader as Direction]}». Стоит
          проверить её или пересмотреть.
        </>
      );
    case "check_agrees":
      return (
        <>
          Наша проверка {exp(f.code)} (идея {idea(f.idea)} «{LABEL[f.claims]}»: {OUTCOME_LABEL[f.outcome]}) согласуется с{" "}
          {majority(s)}.
        </>
      );
    case "check_against":
      return (
        <>
          Наша проверка {exp(f.code)} (идея {idea(f.idea)} «{LABEL[f.claims]}»: {OUTCOME_LABEL[f.outcome]}) расходится с{" "}
          {majority(s)}. Это важный результат — его стоит отразить в методике, а не повторять проверку до другого итога.
        </>
      );
    case "check_other":
      return (
        <>
          Наша проверка {exp(f.code)}: идея {idea(f.idea)} «{LABEL[f.claims]}» не подтвердилась. Статьи говорят «
          {LABEL[s.leader as Direction]}» — этот итог их прямо не подтверждает и не опровергает.
        </>
      );
    case "checks_unlinked":
      return (
        <>
          По пункту есть проверки с итогом ({f.codes.map((c, i) => (
            <span key={c}>
              {i > 0 && ", "}
              {exp(c)}
            </span>
          ))}
          ), но их идея не говорит, как фактор влияет, — сравнить итог со статьями нельзя. Посмотрите их отчёты.
        </>
      );
    case "unchecked":
      return <>У нас это ещё не проверено ни одной проверкой — можно предложить идею по этому пункту.</>;
  }
}

const DOI = /10\.\d{4,9}\/\S+/;

/** «с большинством статей», когда статьи расходятся; иначе — «с тем, что говорят статьи». */
const majority = (s: ArticlesSummary) =>
  s.agreement !== null && s.agreement >= 0.75 ? "тем, что говорят статьи" : "большинством статей";

type Pickable = { id: string; group: Direction; label: string; basis: Parameters<typeof addCrKbBasis>[1] };

/** Статьи сводки как основания предложения: статья с DOI и цитата из неё (правило 5). Без DOI статья
 * «требует источника» и основанием быть не может — её показываем, но отметить нельзя. */
function pickables(s: ArticlesSummary): Pickable[] {
  const out = new Map<string, Pickable>();
  for (const g of s.groups) {
    for (const l of g.links) {
      for (const q of l.quotes) {
        if (out.has(q.doc_id)) continue;
        out.set(q.doc_id, {
          id: q.doc_id,
          group: g.key,
          label: `${q.title || q.doc_id}: «${ruName(l.from)}» — ${l.relation} — «${ruName(l.to)}»`,
          basis: {
            basis_type: "kb_article",
            kbrag_id: q.doc_id,
            kb_path: "esg",
            title: q.title,
            doi: q.url.match(DOI)?.[0] ?? "",
            quote: `«${l.from}» — ${l.relation} — «${l.to}»: «${q.quote}»`,
          },
        });
      }
    }
  }
  return [...out.values()];
}

function draftWhy(s: ArticlesSummary): string {
  const said = s.groups.filter((g) => g.key !== "other").map((g) => `«${LABEL[g.key]}» — ${articles(g.documents)}`);
  const lines = [`По статьям банка о связи «${ruName(s.factor)}» → «${ruName(s.outcome)}»: ${said.join(", ")}.`];
  if (s.agreement !== null && s.leader) {
    lines.push(
      s.agreement >= 0.75
        ? `Статьи в основном согласны: ${pct(s.agreement)} говорят «${LABEL[s.leader]}».`
        : `Статьи расходятся: чаще всего «${LABEL[s.leader]}», ${pct(s.agreement)}.`,
    );
  }
  const done = s.experiments.filter((e) => e.outcome);
  if (done.length) lines.push(`Наши проверки: ${done.map((e) => `${e.code} — ${e.outcome ? OUTCOME_LABEL[e.outcome] : ""}`).join("; ")}.`);
  return lines.join(" ");
}

const toggled = (set: Set<string>, id: string) => {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
};

/** Этап 3: из сводки — предложение изменения пункта с основаниями-цитатами. Принимают люди: рецензия и решение. */
function ProposeFromArticles({ s, section, onDone }: { s: ArticlesSummary; section: Section; onDone: (code: string) => void }) {
  const qc = useQueryClient();
  const options = pickables(s);
  const leaderIds = options.filter((o) => o.group === s.leader && o.basis.doi).slice(0, 3).map((o) => o.id);
  const [title, setTitle] = useState(`${section.number}: что статьи говорят о связи «${ruName(s.factor)}» → «${ruName(s.outcome)}»`);
  const [why, setWhy] = useState(() => draftWhy(s));
  const [text, setText] = useState(section.content);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(leaderIds));
  const doneExps = s.experiments.filter((e) => e.status === "done");
  const [exps, setExps] = useState<Set<string>>(() => new Set(doneExps.map((e) => e.code)));
  // предложение создано, а основание не добавилось — повтор добавляет недостающие основания, а не второе предложение
  const [created, setCreated] = useState("");
  const [added] = useState<Set<string>>(() => new Set());
  const m = useMutation({
    mutationFn: async () => {
      const code = created || (await createCr({ section: section.number, title, description: why, proposed_content: text })).code;
      setCreated(code);
      const failed: string[] = [];
      for (const o of options.filter((x) => picked.has(x.id) && !added.has(x.id))) {
        await addCrKbBasis(code, o.basis).then(() => added.add(o.id), () => failed.push(o.label));
      }
      for (const e of [...exps].filter((x) => !added.has(`exp:${x}`))) {
        await addCrBasis(code, e).then(() => added.add(`exp:${e}`), () => failed.push(e));
      }
      if (failed.length) throw new Error(`${code} создано, но не добавились основания: ${failed.join("; ")}. Добавьте их в предложении.`);
      return code;
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["crs"] }),
    onSuccess: (code) => onDone(code),
  });
  const unchanged = text.trim() === section.content.trim();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <form className="card propose" onSubmit={submit}>
      <h3 className="h3">
        Предложить изменение пункта {section.number} «{section.title}»
      </h3>
      <p className="muted">
        Предложение уйдёт на рецензию как обычно: принять его можно только с одобряющей рецензией и основанием. Цитаты из
        статей ниже станут основаниями — отметьте нужные.
      </p>
      <label className="field">
        Что меняется — коротко
        <input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} />
      </label>
      <label className="field">
        Зачем — что говорят статьи и наши проверки
        <textarea rows={4} value={why} onChange={(e) => setWhy(e.target.value)} />
      </label>
      <label className="field">
        Новый текст пункта
        <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} required />
      </label>
      {unchanged && <p className="muted field-hint">Текст пункта пока не изменён — впишите, что в нём должно поменяться.</p>}
      <fieldset className="field">
        <legend>
          Основания — статьи с DOI и проверки (отмечено {picked.size + exps.size})
        </legend>
        <ul className="list basis-pick">
          {options.map((o) => (
            <li key={o.id}>
              <label>
                <input
                  type="checkbox"
                  checked={picked.has(o.id)}
                  disabled={!o.basis.doi}
                  onChange={() => setPicked(toggled(picked, o.id))}
                />{" "}
                {o.label}
                {!o.basis.doi && <span className="badge st-planned">требует источника — без DOI основанием быть не может</span>}
              </label>
            </li>
          ))}
          {doneExps.map((e) => (
            <li key={e.code}>
              <label>
                <input type="checkbox" checked={exps.has(e.code)} onChange={() => setExps(toggled(exps, e.code))} /> проверка{" "}
                <span className="mono">{e.code}</span> {e.title}
                {e.outcome && <> — {OUTCOME_LABEL[e.outcome]}</>}
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="review-form">
        <button type="submit" className="btn-primary" disabled={m.isPending || unchanged || title.trim().length < 3}>
          {created ? "Добавить основания ещё раз" : "Отправить предложение"}
        </button>
        <button type="button" className="btn-ghost" onClick={() => onDone("")}>
          Отмена
        </button>
      </div>
    </form>
  );
}

function Summary({
  number,
  factor,
  outcome,
  section,
  canPropose,
  openCr,
}: {
  number: string;
  factor: string;
  outcome: string;
  section?: Section;
  canPropose: boolean;
  openCr?: (code: string) => void;
}) {
  const [proposing, setProposing] = useState(false);
  const [sent, setSent] = useState("");
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
          <p className="muted field-hint">
            Считаются статьи за каждой формулировкой: если одна статья пишет о связи по-разному, она войдёт в обе группы.
          </p>
        </>
      )}
      <div className="findings">
        <h3 className="h3">Что это значит для пункта</h3>
        <ul className="list">
          {s.findings.map((f, i) => (
            <li key={`${f.kind}-${i}`}>
              <FindingText f={f} s={s} />
            </li>
          ))}
        </ul>
        <p className="muted field-hint">Это подсказка по статьям и нашим проверкам; решают люди — рецензией и решением по предложению.</p>
      </div>
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
      {canPropose && section && s.total > 0 && !proposing && (
        <div className="review-form">
          <button type="button" className="btn-primary" onClick={() => setProposing(true)}>
            Предложить изменение пункта по статьям
          </button>
          {sent && (
            <span role="status">
              Предложение <span className="mono">{sent}</span> отправлено на рецензию.{" "}
              {openCr && (
                <button type="button" className="btn-ghost" onClick={() => openCr(sent)}>
                  Открыть {sent}
                </button>
              )}
            </span>
          )}
        </div>
      )}
      {proposing && section && (
        <ProposeFromArticles
          s={s}
          section={section}
          onDone={(code) => {
            setProposing(false);
            if (code) setSent(code);
          }}
        />
      )}
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
export function ArticlesSummaryTab({
  initialNode = "",
  canPropose = false,
  openCr,
}: {
  initialNode?: string;
  canPropose?: boolean;
  openCr?: (code: string) => void;
}) {
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
  const netNodes = Array.isArray(concepts.data?.nodes) ? concepts.data.nodes : [];
  const suggested = section ? suggestConcepts(`${section.title} ${section.content}`, netNodes) : [];
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
      {asked && (
        <Summary
          key={`${asked.number}|${asked.factor}|${asked.outcome}`}
          {...asked}
          section={m.data?.sections.find((x) => x.number === asked.number)}
          canPropose={canPropose}
          openCr={openCr}
        />
      )}
    </section>
  );
}
