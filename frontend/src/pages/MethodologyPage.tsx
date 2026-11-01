import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listExperiments } from "../api/experiments";
import { listHypotheses } from "../api/hypotheses";
import {
  addCrBasis,
  type ChangeRequest,
  CHILD_KINDS,
  createCr,
  CR_STATUS_LABEL,
  editCr,
  getMethodology,
  KIND_LABEL,
  listCrs,
  listVersions,
  type NodeKind,
  reviewCr,
  type Section,
  setCrStatus,
  STABILITY_LABEL,
} from "../api/methodology";
import { useMe } from "../auth/useAuth";

const VERDICTS = { approve: "одобрено", changes: "нужны правки", reject: "отклонено" } as const;
const CR_BADGE = { proposed: "st-planned", review: "st-review", accepted: "st-done", rejected: "st-planned" } as const;

function CrTextEditor({ cr, onDone }: { cr: ChangeRequest; onDone: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(cr.title);
  const [newTitle, setNewTitle] = useState(cr.new_title);
  const [description, setDescription] = useState(cr.description);
  const [content, setContent] = useState(cr.proposed_content);
  const m = useMutation({
    mutationFn: () =>
      editCr(cr.code, {
        title,
        description,
        proposed_content: content,
        ...(cr.action === "add" ? { new_title: newTitle } : {}),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["crs"] });
      onDone();
    },
  });
  return (
    <div className="report-editor">
      <label className="field">
        Что меняется
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      {cr.action === "add" && (
        <label className="field">
          Заголовок нового узла
          <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
        </label>
      )}
      <label className="field">
        Почему
        <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="field">
        {cr.action === "add" ? "Текст нового узла" : "Новый текст узла — целиком"}
        <textarea rows={8} value={content} onChange={(e) => setContent(e.target.value)} />
      </label>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="review-form">
        <button type="button" className="btn-primary" disabled={m.isPending || title.trim().length < 3} onClick={() => m.mutate()}>
          Сохранить
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Отмена
        </button>
      </div>
    </div>
  );
}

function CrCard({ cr, role }: { cr: ChangeRequest; role: string | undefined }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(false);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["crs"] });
    void qc.invalidateQueries({ queryKey: ["methodology"] });
    void qc.invalidateQueries({ queryKey: ["versions"] });
  };
  const review = useMutation({
    mutationFn: (v: string) => reviewCr(cr.code, v, text),
    onSuccess: () => {
      setText("");
      refresh();
    },
  });
  const decide = useMutation({
    mutationFn: (s: "accepted" | "rejected") => setCrStatus(cr.code, s),
    onSuccess: refresh,
  });
  const open = cr.status === "proposed" || cr.status === "review";
  const error = review.error ?? decide.error;
  return (
    <article className="card cr" id={`cr-${cr.code}`}>
      <div className="kb-meta">
        <span className="mono">{cr.code}</span> ·{" "}
        {cr.action === "add" ? (
          <>
            добавить {cr.new_kind && KIND_LABEL[cr.new_kind]} в{" "}
            {cr.section ? <span className="mono">{cr.section}</span> : "корень методики"}
          </>
        ) : (
          <>
            изменить <span className="mono">{cr.section}</span>
          </>
        )}
        <span className={`badge ${CR_BADGE[cr.status]}`}>{CR_STATUS_LABEL[cr.status]}</span>
        {cr.target_version && <span className="muted">→ версия {cr.target_version}</span>}
        {cr.source === "qwen" && (
          <span className="muted">
            · черновик Qwen по отчёту{" "}
            {cr.report_experiment ? <Link to={`/experiments/${cr.report_experiment}`}>{cr.report}</Link> : cr.report}
          </span>
        )}
        {cr.source !== "qwen" && cr.author && <span className="muted">· {cr.author}</span>}
      </div>
      {editing ? (
        <CrTextEditor cr={cr} onDone={() => setEditing(false)} />
      ) : (
        <>
          <h3 className="h3">{cr.title}</h3>
          {cr.action === "add" && cr.new_title && <p>Новый узел: «{cr.new_title}»</p>}
          {cr.description && <p className="muted pre-line">{cr.description}</p>}
        </>
      )}
      {open && cr.problems && <p className="blockers">Проверить: {cr.problems}.</p>}
      {cr.editable && !editing && (role === "researcher" || role === "owner") && (
        <div className="review-form">
          <button type="button" className="btn-ghost" onClick={() => setEditing(true)}>
            Править текст
          </button>
        </div>
      )}
      {!editing && cr.proposed_content && (
        <details>
          <summary>{cr.action === "add" ? "Текст нового узла" : "Предлагаемый текст"}</summary>
          <p className="pre-line">{cr.proposed_content}</p>
        </details>
      )}
      <div className="muted">
        Основания:{" "}
        {cr.bases.length === 0
          ? "нет"
          : cr.bases.map((b, i) => (
              <span key={`${b.basis_type}-${b.ref}`}>
                {i > 0 && ", "}
                {b.basis_type === "experiment" ? (
                  <Link to={`/experiments/${b.ref}`} className="mono">
                    {b.ref}
                  </Link>
                ) : (
                  <span className="mono">{b.ref}</span>
                )}{" "}
                {b.valid ? "✓" : "(не годится, пока не завершён или без источника)"}
              </span>
            ))}
      </div>
      {cr.reviews.length > 0 && (
        <ul className="list">
          {cr.reviews.map((r) => (
            <li key={r.created_at}>
              <strong>{r.reviewer}</strong> — {VERDICTS[r.verdict]}
              {r.text && <span className="muted">: {r.text}</span>}
            </li>
          ))}
        </ul>
      )}
      {open && cr.blockers.length > 0 && <p className="blockers">Принять нельзя: {cr.blockers.join("; ")}.</p>}
      {open && (role === "reviewer" || role === "owner") && (
        <div className="review-form">
          <label className="field inline grow">
            Комментарий рецензента
            <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="button" className="btn-ghost" disabled={review.isPending} onClick={() => review.mutate("approve")}>
            Одобрить
          </button>
          <button type="button" className="btn-ghost" disabled={review.isPending} onClick={() => review.mutate("changes")}>
            Нужны правки
          </button>
          <button type="button" className="btn-ghost" disabled={review.isPending} onClick={() => review.mutate("reject")}>
            Отклонить
          </button>
        </div>
      )}
      {open && role === "owner" && (
        <div className="review-form">
          <button
            type="button"
            className="btn-primary"
            disabled={cr.blockers.length > 0 || decide.isPending}
            onClick={() => decide.mutate("accepted")}
          >
            Принять
          </button>
          <button type="button" className="btn-ghost" disabled={decide.isPending} onClick={() => decide.mutate("rejected")}>
            Отклонить CR
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

/** Что предлагают: изменить узел или добавить под ним новый (parent null — корень методики). */
type Draft = { action: "edit"; node: Section } | { action: "add"; parent: Section | null; kind: NodeKind };

function CrForm({ draft, onDone }: { draft: Draft; onDone: () => void }) {
  const qc = useQueryClient();
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const original = draft.action === "edit" ? draft.node.content : "";
  const [title, setTitle] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [description, setDescription] = useState("");
  const [proposed, setProposed] = useState(original);
  const [basis, setBasis] = useState("");
  const [created, setCreated] = useState(""); // CR создан, а основание не добавилось — не создавать дубль
  const m = useMutation({
    mutationFn: async () => {
      const cr = await createCr(
        draft.action === "edit"
          ? { section: draft.node.number, title, description, proposed_content: proposed }
          : {
              section: draft.parent?.number ?? "",
              action: "add",
              new_kind: draft.kind,
              new_title: newTitle,
              title,
              description,
              proposed_content: proposed,
            },
      );
      setCreated(cr.code);
      void qc.invalidateQueries({ queryKey: ["crs"] });
      if (basis) {
        try {
          await addCrBasis(cr.code, basis);
        } catch (err) {
          throw new Error(`${cr.code} создан, но основание не добавлено: ${err instanceof Error ? err.message : String(err)}`);
        }
      }
      return cr;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["crs"] });
      onDone();
    },
  });
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    m.mutate();
  };
  const where =
    draft.action === "edit"
      ? `${KIND_LABEL[draft.node.kind]} ${draft.node.number} «${draft.node.title}»`
      : `${KIND_LABEL[draft.kind]} в ${draft.parent ? `${draft.parent.number} «${draft.parent.title}»` : "корень методики"}`;
  const unchanged = draft.action === "edit" && proposed.trim() === original.trim();
  return (
    <form className="card propose" onSubmit={submit}>
      <h3 className="h3">
        {draft.action === "edit" ? "Изменить" : "Добавить"}: {where}
      </h3>
      <p className="muted">
        Методика меняется только через CR: его принимает owner после одобряющей рецензии и если есть основание —
        завершённый эксперимент, факт или статья базы знаний с источником.
      </p>
      {draft.action === "add" && (
        <label className="field">
          Заголовок нового узла
          <input
            value={newTitle}
            onChange={(ev) => setNewTitle(ev.target.value)}
            required
            minLength={3}
            maxLength={512}
            placeholder={draft.kind === "task" ? "Задание 1. …" : draft.kind === "variant" ? "Вариант 4: …" : "Название раздела"}
          />
        </label>
      )}
      <label className="field">
        Что меняется — коротко
        <input value={title} onChange={(ev) => setTitle(ev.target.value)} required minLength={3} />
      </label>
      <label className="field">
        Зачем — что показали эксперименты или статьи
        <textarea rows={3} value={description} onChange={(ev) => setDescription(ev.target.value)} />
      </label>
      <label className="field">
        {draft.action === "edit" ? "Новый текст" : "Текст нового узла"}
        <textarea rows={6} value={proposed} onChange={(ev) => setProposed(ev.target.value)} required />
      </label>
      <label className="field">
        Основание — эксперимент (можно добавить позже)
        <select value={basis} onChange={(ev) => setBasis(ev.target.value)}>
          <option value="">— без основания пока —</option>
          {(exps.data ?? []).map((e) => (
            <option key={e.code} value={e.code}>
              {e.code} · {e.title.slice(0, 70)}
            </option>
          ))}
        </select>
      </label>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="review-form">
        {created ? (
          <button type="button" className="btn-primary" onClick={onDone}>
            Закрыть
          </button>
        ) : (
          <button type="submit" className="btn-primary" disabled={m.isPending || unchanged}>
            Отправить на рецензию
          </button>
        )}
        <button type="button" className="btn-ghost" onClick={onDone}>
          Отмена
        </button>
      </div>
    </form>
  );
}

interface TreeCtx {
  nodes: Section[];
  canPropose: boolean;
  draft: Draft | null;
  setDraft: (d: Draft | null) => void;
  work: Map<string, { exps: string[]; hyps: string[] }>;
  openCrs: Map<string, string[]>;
}

function NodeActions({ node, ctx }: { node: Section | null; ctx: TreeCtx }) {
  if (!ctx.canPropose) return null;
  const kinds = CHILD_KINDS[node?.kind ?? ""];
  return (
    <div className="node-actions">
      {node && (
        <button type="button" className="link-btn" onClick={() => ctx.setDraft({ action: "edit", node })}>
          изменить
        </button>
      )}
      {kinds.map((k) => (
        <button key={k} type="button" className="link-btn" onClick={() => ctx.setDraft({ action: "add", parent: node, kind: k })}>
          + {KIND_LABEL[k]}
        </button>
      ))}
    </div>
  );
}

function DraftHere({ node, ctx }: { node: Section | null; ctx: TreeCtx }) {
  const d = ctx.draft;
  if (!d) return null;
  const target = d.action === "edit" ? d.node.number : (d.parent?.number ?? "");
  if (target !== (node?.number ?? "")) return null;
  return <CrForm key={`${d.action}-${target}-${d.action === "add" ? d.kind : ""}`} draft={d} onDone={() => ctx.setDraft(null)} />;
}

function Node({ node, ctx }: { node: Section; ctx: TreeCtx }) {
  const children = ctx.nodes.filter((n) => n.parent === node.number);
  const sections = children.filter((n) => n.kind === "section");
  const nested = children.filter((n) => n.kind !== "section");
  const work = ctx.work.get(node.number);
  const crs = ctx.openCrs.get(node.number) ?? [];
  const hasLinks = Boolean(work?.exps.length || work?.hyps.length || crs.length);
  const head = (
    <>
      <span className="mono node-num">{node.number}</span> <strong>{node.title}</strong>{" "}
      <span className={`badge stab-${node.stability}`}>{STABILITY_LABEL[node.stability]}</span>
    </>
  );
  const body = (
    <>
      <p className="pre-line node-text">{node.content || <span className="muted">Текста нет.</span>}</p>
      {hasLinks && (
        <div className="node-links muted">
          {work?.hyps.map((h) => (
            <Link key={h} to="/hypotheses" className="mono">
              {h}
            </Link>
          ))}
          {work?.exps.map((e) => (
            <Link key={e} to={`/experiments/${e}`} className="mono">
              {e}
            </Link>
          ))}
          {crs.map((c) => (
            <a key={c} href={`#cr-${c}`} className="mono">
              {c} (открыт)
            </a>
          ))}
        </div>
      )}
      <NodeActions node={node} ctx={ctx} />
      <DraftHere node={node} ctx={ctx} />
      {sections.length > 0 && (
        <div className="node-sections">
          {sections.map((s) => (
            <Node key={s.number} node={s} ctx={ctx} />
          ))}
        </div>
      )}
      {nested.map((n) => (
        <Node key={n.number} node={n} ctx={ctx} />
      ))}
    </>
  );
  if (node.kind === "section") {
    return (
      <section className="node node-section" aria-label={`Раздел ${node.number}`}>
        <div className="node-head">{head}</div>
        {body}
      </section>
    );
  }
  return (
    <details className={`node node-${node.kind}`} open>
      <summary className="node-head">
        <span className="muted node-kind">{KIND_LABEL[node.kind]}</span> {head}
      </summary>
      {body}
    </details>
  );
}

export function Methodology() {
  const me = useMe();
  const [draft, setDraft] = useState<Draft | null>(null);
  const m = useQuery({ queryKey: ["methodology"], queryFn: getMethodology });
  const crs = useQuery({ queryKey: ["crs"], queryFn: listCrs });
  const versions = useQuery({ queryKey: ["versions"], queryFn: listVersions });
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const hyps = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const nodes = Array.isArray(m.data?.sections) ? m.data.sections : [];
  const crList = Array.isArray(crs.data) ? crs.data : [];
  const versionList = Array.isArray(versions.data) ? versions.data : [];
  // ссылка вида /methodology#cr-CR-02 (из отчёта): прокрутить к CR, когда список загрузился
  const crsLoaded = crs.isSuccess;
  useEffect(() => {
    if (crsLoaded && window.location.hash.startsWith("#cr-")) {
      document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "start" });
    }
  }, [crsLoaded]);
  const canPropose = me.data?.role === "researcher" || me.data?.role === "owner";
  // что относится к узлу: гипотезы, эксперименты, открытые CR
  const work = new Map<string, { exps: string[]; hyps: string[] }>();
  const slot = (n: string) => {
    const w = work.get(n) ?? { exps: [], hyps: [] };
    work.set(n, w);
    return w;
  };
  for (const e of exps.data ?? []) if (e.methodology_node) slot(e.methodology_node).exps.push(e.code);
  for (const h of hyps.data ?? []) if (h.methodology_node) slot(h.methodology_node).hyps.push(h.code);
  const openCrs = new Map<string, string[]>();
  for (const c of crList) {
    if (c.status === "proposed" || c.status === "review") openCrs.set(c.section, [...(openCrs.get(c.section) ?? []), c.code]);
  }
  const ctx: TreeCtx = { nodes, canPropose, draft, setDraft, work, openCrs };
  const common = nodes.filter((n) => !n.parent && n.kind === "section");
  const directions = nodes.filter((n) => !n.parent && n.kind !== "section");
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">МЕТОДОЛОГИЯ · ВЕРСИЯ {m.data?.version ?? "…"}</span>
        <h1 className="page-title">Методология</h1>
        <p className="lead">
          Постановка лаборатории: направления, варианты и задания, у каждого — свои разделы. Общие разделы действуют на
          всю методику, раздел варианта — на все его задания. Изменение и новый узел проходят через CR: нужно основание
          (завершённый эксперимент, факт или статья базы знаний) и одобряющая рецензия.
        </p>
        <div>
          <a className="btn-ghost" href="/api/methodology/export.docx">
            Скачать .docx
          </a>
        </div>
      </section>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="methodology-layout">
        <div className="tree">
          <section className="card">
            <div className="viz-head">
              <h2 className="h2">Общие разделы</h2>
              <NodeActions node={null} ctx={ctx} />
            </div>
            <DraftHere node={null} ctx={ctx} />
            {m.isSuccess && common.length === 0 && <p className="muted">Общих разделов нет.</p>}
            {common.map((s) => (
              <Node key={s.number} node={s} ctx={ctx} />
            ))}
          </section>
          {directions.map((d) => (
            <div key={d.number} className="card">
              <Node node={d} ctx={ctx} />
            </div>
          ))}
        </div>
        <section className="cr-board">
          <h2 className="h2">Предложения изменений</h2>
          {crList.map((cr) => (
            <CrCard key={cr.code} cr={cr} role={me.data?.role} />
          ))}
          {crs.isSuccess && crList.length === 0 && <p className="muted">Предложений нет.</p>}
        </section>
      </div>
      <section className="card">
        <h2 className="h2">История версий</h2>
        <ul className="list">
          {versionList.map((v) => (
            <li key={v.version}>
              <span className="mono">{v.version}</span> — {v.notes}{" "}
              <span className="muted">{new Date(v.created_at).toLocaleDateString("ru-RU")}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
