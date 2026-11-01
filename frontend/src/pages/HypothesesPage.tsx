import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  decideHypothesis,
  experimentFromHypothesis,
  H_BADGE,
  H_STATUS_LABEL,
  type HStatus,
  type Hypothesis,
  type KbRefIn,
  listHypotheses,
  proposeHypothesis,
} from "../api/hypotheses";
import { useMe } from "../auth/useAuth";
import { NodeSelect } from "../components/NodeSelect";
import { ProposalPanel } from "../components/ProposalPanel";

/** Опора, переданная со страницы базы знаний («Предложить гипотезу по этой статье»). */
export interface ProposeState {
  ref?: KbRefIn;
}

function ProposeForm({ initialRef, onDone }: { initialRef?: KbRefIn; onDone: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [statement, setStatement] = useState("");
  const [rationale, setRationale] = useState("");
  const [direction, setDirection] = useState("");
  const [node, setNode] = useState("");
  const [refs, setRefs] = useState<KbRefIn[]>(initialRef ? [initialRef] : []);
  const m = useMutation({
    mutationFn: () => proposeHypothesis({ title, statement, rationale, direction, methodology_node: node, refs }),
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
      <h2 className="h2">Предложить гипотезу</h2>
      <p className="muted">
        Гипотезу может предложить любой участник. Рецензент примет её к проверке или объяснит, почему отклонил;
        принятую исследователь проверит экспериментом.
      </p>
      <label className="field">
        Коротко, о чём гипотеза
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
      <label className="field">
        Направление
        <select value={direction} onChange={(e) => setDirection(e.target.value)}>
          <option value="">не знаю</option>
          <option value="Напр. 1">Напр. 1 — ESG и финансовые результаты, поддержка решений</option>
          <option value="Напр. 2">Напр. 2 — ESG-рейтинги и методики</option>
          <option value="Методы">Методы</option>
        </select>
      </label>
      {refs.length > 0 && (
        <div className="muted">
          Опора в базе знаний:
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
        Чтобы опереться на статью, найдите её в <Link to="/knowledge">базе знаний</Link> и нажмите «Предложить
        гипотезу по этой статье».
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

function HypothesisCard({ h, role }: { h: Hypothesis; role: string | undefined }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [note, setNote] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["hypotheses"] });
  const decide = useMutation({
    mutationFn: (s: "accepted" | "rejected") => decideHypothesis(h.code, s, note),
    onSuccess: refresh,
  });
  const start = useMutation({
    mutationFn: () => experimentFromHypothesis(h.code),
    onSuccess: (r) => {
      refresh();
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      navigate(`/experiments/${r.experiment}`);
    },
  });
  const canDecide = role === "reviewer" || role === "owner";
  const canTest = role === "researcher" || role === "owner";
  const error = decide.error ?? start.error;
  return (
    <article className="card cr">
      <div className="kb-meta">
        <span className="mono">{h.code}</span>
        {h.direction && <span>· {h.direction}</span>}
        {h.methodology_node && (
          <Link to="/methodology" className="mono">
            · {h.methodology_node}
          </Link>
        )}
        <span className={`badge ${H_BADGE[h.status]}`}>{H_STATUS_LABEL[h.status]}</span>
        {h.source === "qwen" && <span className="badge st-running">предложила Qwen</span>}
        <span className="muted">
          {h.source === "qwen" ? "по статьям и графу базы знаний" : `предложил ${h.author || "—"}`},{" "}
          {new Date(h.created_at).toLocaleDateString("ru-RU")}
        </span>
      </div>
      <h3 className="h3">{h.title}</h3>
      <p>{h.statement}</p>
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
      )}
      {h.decision_note && (
        <p className="muted">
          Решение ({h.decided_by}): {h.decision_note}
        </p>
      )}
      {h.experiment && (
        <p>
          Проверяется в <Link to={`/experiments/${h.experiment}`} className="mono">{h.experiment}</Link>
        </p>
      )}
      {h.status === "proposed" && canDecide && (
        <div className="review-form">
          <label className="field inline grow">
            Комментарий (обязателен при отклонении)
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="button" className="btn-primary" disabled={decide.isPending} onClick={() => decide.mutate("accepted")}>
            Принять к проверке
          </button>
          <button type="button" className="btn-ghost" disabled={decide.isPending} onClick={() => decide.mutate("rejected")}>
            Отклонить
          </button>
        </div>
      )}
      <ProposalPanel code={h.code} status={h.status} canDecide={canTest} />
      {h.status === "accepted" && canTest && (
        <div className="review-form">
          <button type="button" className="btn-ghost" onClick={() => start.mutate()} disabled={start.isPending}>
            Создать эксперимент вручную
          </button>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
    </article>
  );
}

const FILTERS: Array<{ key: HStatus | "all" | "qwen"; label: string }> = [
  { key: "all", label: "Все" },
  { key: "qwen", label: "От Qwen" },
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
  const [filter, setFilter] = useState<HStatus | "all" | "qwen">("all");
  const q = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const all = Array.isArray(q.data) ? q.data : [];
  const match = (h: Hypothesis, f: HStatus | "all" | "qwen") => f === "all" || (f === "qwen" ? h.source === "qwen" : h.status === f);
  const shown = all.filter((h) => match(h, filter));
  const close = () => {
    setProposing(false);
    navigate(location.pathname, { replace: true, state: null });
  };
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">ГИПОТЕЗЫ</span>
        <h1 className="page-title">Гипотезы</h1>
        <p className="lead">
          Начало цикла: база знаний подсказывает гипотезу, рецензент принимает её к проверке, эксперимент
          подтверждает или отклоняет, а результат становится основанием изменения методологии.
        </p>
        {!proposing && (
          <div>
            <button type="button" className="btn-primary" onClick={() => setProposing(true)}>
              Предложить гипотезу
            </button>
          </div>
        )}
      </section>
      {proposing && <ProposeForm initialRef={initialRef} onDone={close} />}
      <div className="filters" role="group" aria-label="Статус гипотезы">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={filter === f.key ? "chip active" : "chip"}
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
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
          <p className="muted">{all.length === 0 ? "Гипотез пока нет — предложите первую." : "С таким статусом гипотез нет."}</p>
        )}
      </div>
    </>
  );
}
