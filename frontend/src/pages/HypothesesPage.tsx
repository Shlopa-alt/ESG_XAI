import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  decideHypothesis,
  type Effect,
  EFFECT_LABEL,
  H_BADGE,
  H_STATUS_LABEL,
  type HStatus,
  type Hypothesis,
  type KbRefIn,
  listHypotheses,
  linkType,
  proposeHypothesis,
  setHypothesisWeight,
  similarHypotheses,
  TARGET_KIND_LABEL,
  type TargetKind,
  type Weight,
  WEIGHT_LABEL,
  WEIGHTS,
} from "../api/hypotheses";
import { kbSearch } from "../api/kb";
import { useMe } from "../auth/useAuth";
import { NodeSelect } from "../components/NodeSelect";
import { ProposalPanel } from "../components/ProposalPanel";
import { canReview, canRun, HypothesisPath, hypothesisNext, NextStep } from "../components/Ux";
import { refFromHit } from "./KbLive";

/** Опора, переданная со страницы базы знаний («Предложить гипотезу по этой статье»). */
export interface ProposeState {
  ref?: KbRefIn;
}

const ARTICLES_SHOWN = 3;

/** Есть ли похожее: уже предложенные идеи и статьи банка о том же. Ничего не отправляет. */
function SimilarCheck({ title, statement, refs, onAddRef }: {
  title: string;
  statement: string;
  refs: KbRefIn[];
  onAddRef: (r: KbRefIn) => void;
}) {
  const check = useMutation({
    mutationFn: async () => {
      const q = `${title} ${statement}`.trim();
      // статьи ищутся по смыслу: русский запрос находит и английские статьи
      const [ideas, hits] = await Promise.all([similarHypotheses(title, statement), kbSearch(q, "esg").catch(() => null)]);
      const seen = new Set<string>();
      const articles = (hits ?? []).filter((h) => !seen.has(h.doc_id) && seen.add(h.doc_id)).slice(0, ARTICLES_SHOWN);
      return { ideas, articles, bankDown: hits === null };
    },
  });
  const ready = title.trim().length >= 5;
  const r = check.data;
  return (
    <div className="similar">
      <div className="review-form">
        <button type="button" className="btn-ghost" disabled={!ready || check.isPending} onClick={() => check.mutate()}>
          {check.isPending ? "Ищем похожее…" : "Проверить, есть ли похожее"}
        </button>
        <span className="muted">{ready ? "Найдём похожие идеи и статьи банка о том же." : "Сначала коротко опишите идею."}</span>
      </div>
      {check.isError && (
        <p className="error" role="alert">
          Не удалось проверить: {check.error.message}
        </p>
      )}
      {r && (
        <div className="similar-result" aria-live="polite">
          <h3 className="h3">Похожие идеи</h3>
          {r.ideas.length === 0 ? (
            <p className="muted">Похожих среди предложенных идей нет.</p>
          ) : (
            <ul className="list">
              {r.ideas.map((i) => (
                <li key={i.code}>
                  <a href={`#${i.code}`} className="mono">
                    {i.code}
                  </a>{" "}
                  {i.title} <span className={`badge ${H_BADGE[i.status]}`}>{H_STATUS_LABEL[i.status]}</span>
                  {i.source === "qwen" && <span className="muted"> · предложил ИИ-помощник</span>}
                </li>
              ))}
            </ul>
          )}
          {r.ideas.length > 0 && (
            <p className="muted">Если это та же идея, лучше дополнить её, чем предлагать заново. Если ваша отличается — напишите в обосновании чем.</p>
          )}
          <h3 className="h3">Статьи о том же</h3>
          {r.bankDown && <p className="muted">Банк статей сейчас недоступен, статьи не проверены.</p>}
          {!r.bankDown && r.articles.length === 0 && <p className="muted">В банке статей ничего близкого не нашлось.</p>}
          {r.articles.length > 0 && (
            <ul className="list">
              {r.articles.map((a) => {
                const taken = refs.some((x) => x.kbrag_id === a.doc_id);
                return (
                  <li key={a.doc_id}>
                    <Link to={`/knowledge/article/${encodeURIComponent(a.doc_id)}`}>{a.title || a.doc_id}</Link>
                    {a.year && <span className="muted"> · {a.year}</span>}
                    {a.pages.length > 0 && <span className="muted mono"> · с. {a.pages.join(", ")}</span>}
                    <p className="muted similar-quote">{a.text.length > 240 ? `${a.text.slice(0, 240).replace(/\s+\S*$/, "")}…` : a.text}</p>
                    <button type="button" className="link-btn" disabled={taken}
                      onClick={() => onAddRef(refFromHit(a, "esg"))}>
                      {taken ? "уже источник" : "взять источником"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Выбор силы связи; пустое значение — «не знаю». */
function WeightSelect({ value, onChange, id }: { value: Weight | null; onChange: (w: Weight | null) => void; id?: string }) {
  return (
    <select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value ? (Number(e.target.value) as Weight) : null)}>
      <option value="">не знаю</option>
      {WEIGHTS.map((w) => (
        <option key={w} value={w}>
          {w} — {WEIGHT_LABEL[w]}
        </option>
      ))}
    </select>
  );
}

/** Сила связи на карточке: кто поставил; рецензент может изменить. */
function WeightFact({ h, canChange }: { h: Hypothesis; canChange: boolean }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState<Weight | null>(h.weight);
  const save = useMutation({
    mutationFn: () => setHypothesisWeight(h.code, value),
    onSuccess: () => {
      setEditing(false);
      void qc.invalidateQueries({ queryKey: ["hypotheses"] });
    },
  });
  const selectId = `weight-${h.code}`;
  return (
    <div>
      <dt>{editing ? <label htmlFor={selectId}>Сила связи</label> : "Сила связи"}</dt>
      <dd>
        {editing ? (
          <span className="weight-edit">
            <WeightSelect id={selectId} value={value} onChange={setValue} />
            <button type="button" className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
              Сохранить
            </button>
            <button type="button" className="btn-ghost" onClick={() => { setEditing(false); setValue(h.weight); }}>
              Отмена
            </button>
            {save.error && <span role="alert" className="error">{save.error.message}</span>}
          </span>
        ) : (
          <>
            {h.weight ? (
              <>
                {h.weight} — {WEIGHT_LABEL[h.weight]}
                {h.weight_set_by && <span className="muted"> · поставил {h.weight_set_by}</span>}
              </>
            ) : (
              <span className="muted">не указана</span>
            )}
            {canChange && (
              <button type="button" className="btn-ghost weight-change" onClick={() => setEditing(true)}>
                Изменить
              </button>
            )}
          </>
        )}
      </dd>
    </div>
  );
}

function ProposeForm({ initialRef, onDone }: { initialRef?: KbRefIn; onDone: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [statement, setStatement] = useState("");
  const [rationale, setRationale] = useState("");
  const [direction, setDirection] = useState("");
  const [node, setNode] = useState("");
  const [effect, setEffect] = useState<Effect | "">("");
  const [target, setTarget] = useState<TargetKind | "">("");
  const [weight, setWeight] = useState<Weight | null>(null);
  const [refs, setRefs] = useState<KbRefIn[]>(initialRef ? [initialRef] : []);
  const m = useMutation({
    mutationFn: () => proposeHypothesis({ title, statement, rationale, direction, methodology_node: node, effect, target_kind: target, weight, refs }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hypotheses"] });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <form className="card propose" onSubmit={submit}>
      <h2 className="h2">Предложить идею</h2>
      <p className="muted">
        Идею может предложить любой участник. Рецензент примет её к проверке или объяснит, почему отклонил;
        принятую исследователь проверит расчётом.
      </p>
      <label className="field">
        Коротко, о чём идея
        <input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={5} maxLength={512}
          placeholder="Например: ESG-раскрытие снижает стоимость долга" />
      </label>
      <label className="field">
        Проверяемое утверждение
        <textarea value={statement} onChange={(e) => setStatement(e.target.value)} required minLength={10} rows={3}
          placeholder="Что именно должно подтвердиться данными: какой фактор, как влияет, на что, на каком горизонте" />
      </label>
      <label className="field">
        Обоснование
        <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={3}
          placeholder="Почему так думаете: статьи, наблюдения, практика компаний" />
      </label>
      <label className="field" htmlFor="h-node">
        Задание методики
        <NodeSelect id="h-node" value={node} onChange={setNode} />
      </label>
      <fieldset className="field-row">
        <legend>Тип связи: как фактор влияет и на какие показатели</legend>
        <label className="field">
          Как влияет
          <select value={effect} onChange={(e) => setEffect(e.target.value as Effect | "")}>
            <option value="">не знаю</option>
            {(Object.keys(EFFECT_LABEL) as Effect[]).map((k) => (
              <option key={k} value={k}>
                {EFFECT_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          На какие показатели
          <select value={target} onChange={(e) => setTarget(e.target.value as TargetKind | "")}>
            <option value="">не знаю</option>
            {(Object.keys(TARGET_KIND_LABEL) as TargetKind[]).map((k) => (
              <option key={k} value={k}>
                {TARGET_KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <label className="field" htmlFor="h-weight">
          Сила связи
          <WeightSelect id="h-weight" value={weight} onChange={setWeight} />
        </label>
        <p className="muted field-hint">
          Сила связи — насколько, по-вашему, заметно влияние: слабая, средняя или сильная. Рецензент может её изменить.
          Нефинансовые результаты — например, ESG-рейтинг или выбросы. Единого перечня нет, поэтому уточните в утверждении,
          какой именно показатель.
        </p>
      </fieldset>
      <label className="field">
        Направление
        <select value={direction} onChange={(e) => setDirection(e.target.value)}>
          <option value="">не знаю</option>
          <option value="Напр. 1">Напр. 1 — ESG и финансовые результаты, поддержка решений</option>
          <option value="Напр. 2">Напр. 2 — ESG-рейтинги и методики</option>
          <option value="Методы">Методы</option>
        </select>
      </label>
      <SimilarCheck title={title} statement={statement} refs={refs} onAddRef={(r) => setRefs([...refs, r])} />
      {refs.length > 0 && (
        <div className="muted">
          Источник в банке статей:
          <ul className="list">
            {refs.map((r) => (
              <li key={r.kbrag_id}>
                {r.title || r.kbrag_id} {r.doi && <span className="mono">· DOI {r.doi}</span>}{" "}
                <button type="button" className="link-btn" onClick={() => setRefs(refs.filter((x) => x !== r))}>
                  убрать
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="muted">
        Чтобы опереться на статью, найдите её в <Link to="/knowledge">банке статей</Link> и нажмите «Предложить
        идею по этой статье».
      </p>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="review-form">
        <button type="submit" className="btn-primary" disabled={m.isPending}>
          Отправить на рассмотрение
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Отмена
        </button>
      </div>
    </form>
  );
}

/** Ждёт ли гипотеза действия именно от этой роли. */
const needsMe = (h: Hypothesis, role: string | undefined) =>
  (h.status === "proposed" && canReview(role)) || (h.status === "accepted" && canRun(role));

function HypothesisCard({ h, role }: { h: Hypothesis; role: string | undefined }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState(false);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["hypotheses"] });
  const decide = useMutation({
    mutationFn: (s: "accepted" | "rejected") => decideHypothesis(h.code, s, note),
    onSuccess: refresh,
  });
  const canDecide = canReview(role);
  const error = decide.error;
  const rejectWithNote = () => {
    if (!note.trim()) {
      setNoteError(true);
      return;
    }
    decide.mutate("rejected");
  };
  return (
    <article className="card cr" id={h.code}>
      <div className="kb-meta">
        <span className="mono">{h.code}</span>
        {h.direction && <span>· {h.direction}</span>}
        {h.methodology_node && (
          <Link to="/methodology" className="mono">
            · {h.methodology_node}
          </Link>
        )}
        <span className={`badge ${H_BADGE[h.status]}`}>{H_STATUS_LABEL[h.status]}</span>
        {h.source === "qwen" && <span className="badge st-running">предложил ИИ-помощник</span>}
        <span className="muted">
          {h.source === "qwen" ? "по статьям банка" : h.author ? `предложил ${h.author}` : "автор не записан"},{" "}
          {new Date(h.created_at).toLocaleDateString("ru-RU")}
        </span>
      </div>
      <h3 className="h3">{h.title}</h3>
      <p>{h.statement}</p>
      <dl className="idea-facts">
        <div>
          <dt>Задание методики</dt>
          <dd>
            {h.methodology_node ? (
              <Link to="/methodology">
                <span className="mono">{h.methodology_node}</span>
                {h.methodology_node_title && ` ${h.methodology_node_title}`}
              </Link>
            ) : (
              <span className="muted">не указано</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Тип связи</dt>
          <dd>{linkType(h.effect, h.target_kind) || <span className="muted">не указан</span>}</dd>
        </div>
        <WeightFact h={h} canChange={canDecide} />
      </dl>
      <HypothesisPath status={h.status} />
      <NextStep
        action={
          h.status === "accepted" && canRun(role) ? (
            <Link to={`/run?h=${encodeURIComponent(h.code)}`} className="btn-primary">
              Проверить идею
            </Link>
          ) : undefined
        }
      >
        {hypothesisNext(h.status, role, h.code, h.experiment)}
      </NextStep>
      {h.rationale && <p className="muted">Обоснование: {h.rationale}</p>}
      {h.source === "qwen" && (h.suggested.dataset || h.suggested.method || h.suggested.data_needed) && (
        <p className="muted">
          Проверить:{" "}
          {h.suggested.dataset && (
            <>
              на <Link to={`/datasets/${h.suggested.dataset}`} className="mono">{h.suggested.dataset}</Link>
              {h.suggested.method ? ", " : ""}
            </>
          )}
          {h.suggested.method && <>метод: {h.suggested.method}</>}
          {h.suggested.data_needed && <> · нужны данные: {h.suggested.data_needed}</>}
        </p>
      )}
      {h.refs.length > 0 && (
        <details open={h.status === "proposed"}>
          <summary>Источники в банке статей ({h.refs.length})</summary>
          <ul className="list muted">
            {h.refs.map((r) => (
              <li key={r.kbrag_id}>
                {r.kind === "article" ? (
                  <Link to={`/knowledge/article/${encodeURIComponent(r.kbrag_id)}`}>{r.title || r.kbrag_id}</Link>
                ) : (
                  r.title || r.kbrag_id
                )}{" "}
                {r.doi && <span className="mono">· DOI {r.doi}</span>}
                {r.quote && <q> {r.quote}</q>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {h.decision_note && (
        <p className="muted">
          Решение{h.decided_by ? ` (${h.decided_by})` : ""}: {h.decision_note}
        </p>
      )}
      {h.status === "proposed" && canDecide && (
        <div className="review-form">
          <label className="field inline grow">
            Комментарий (обязателен при отклонении — его увидит автор)
            <textarea
              rows={2}
              value={note}
              aria-invalid={noteError}
              onChange={(e) => {
                setNote(e.target.value);
                setNoteError(false);
              }}
            />
            {noteError && <span className="error">Напишите, почему отклоняете.</span>}
          </label>
          <button type="button" className="btn-primary" disabled={decide.isPending} onClick={() => decide.mutate("accepted")}>
            Принять к проверке
          </button>
          <button type="button" className="btn-ghost" disabled={decide.isPending} onClick={rejectWithNote}>
            Отклонить
          </button>
        </div>
      )}
      {/* править и одобрять предложение ИИ-помощника — в мастере на странице расчёта; здесь только история */}
      {h.status !== "accepted" && <ProposalPanel code={h.code} status={h.status} />}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
    </article>
  );
}

type HFilter = HStatus | "all" | "qwen" | "mine";
const FILTERS: Array<{ key: HFilter; label: string }> = [
  { key: "mine", label: "Ждут моего действия" },
  { key: "all", label: "Все" },
  { key: "qwen", label: "От ИИ-помощника" },
  { key: "proposed", label: "Ждут решения" },
  { key: "accepted", label: "Приняты" },
  { key: "testing", label: "Проверяются" },
  { key: "tested", label: "Проверены" },
  { key: "rejected", label: "Отклонены" },
];

export function Hypotheses() {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const initialRef = (location.state as ProposeState | null)?.ref;
  const [proposing, setProposing] = useState(Boolean(initialRef));
  const [filter, setFilter] = useState<HFilter>("all");
  const q = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const all = Array.isArray(q.data) ? q.data : [];
  const role = me.data?.role;
  const match = (h: Hypothesis, f: HFilter) =>
    f === "all" || (f === "qwen" ? h.source === "qwen" : f === "mine" ? needsMe(h, role) : h.status === f);
  // если что-то ждёт пользователя — сразу показываем это
  const mineCount = all.filter((h) => needsMe(h, role)).length;
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (touched) return;
    // решил последнюю — не оставляем пустой список
    setFilter((f) => (mineCount > 0 ? "mine" : f === "mine" ? "all" : f));
  }, [mineCount, touched]);
  const shown = all.filter((h) => match(h, filter));
  const close = () => {
    setProposing(false);
    navigate(location.pathname, { replace: true, state: null });
  };
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">ИДЕИ ДЛЯ ПРОВЕРКИ</span>
        <h1 className="page-title">Идеи для проверки</h1>
        <p className="lead">
          Идея, или гипотеза, это утверждение, которое можно проверить расчётом. Её предлагает человек или ИИ-помощник, а
          рецензент решает, стоит ли проверять.
        </p>
        {!proposing && (
          <div>
            <button type="button" className="btn-primary" onClick={() => setProposing(true)}>
              Предложить идею
            </button>
          </div>
        )}
      </section>
      {proposing && <ProposeForm initialRef={initialRef} onDone={close} />}
      <div className="filters" role="group" aria-label="Статус идеи">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={filter === f.key ? "chip active" : "chip"}
            aria-pressed={filter === f.key}
            onClick={() => {
              setTouched(true);
              setFilter(f.key);
            }}
          >
            {f.label} ({all.filter((h) => match(h, f.key)).length})
          </button>
        ))}
      </div>
      {q.isError && (
        <p className="error" role="alert">
          {q.error.message}
        </p>
      )}
      <div className="cr-board">
        {shown.map((h) => (
          <HypothesisCard key={h.code} h={h} role={me.data?.role} />
        ))}
        {q.isSuccess && shown.length === 0 && (
          <p className="muted">{all.length === 0 ? "Идей пока нет — предложите первую." : "С таким статусом идей нет."}</p>
        )}
      </div>
    </>
  );
}
