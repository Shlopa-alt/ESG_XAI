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
import { plural } from "../components/Ux";

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
          Название нового пункта
          <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
        </label>
      )}
      <label className="field">
        Почему
        <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="field">
        {cr.action === "add" ? "Текст нового пункта" : "Новый текст пункта целиком"}
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
            {cr.section ? <span className="mono">{cr.section}</span> : "всю методику"}
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
            · черновик ИИ-помощника по отчёту{" "}
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
          {cr.action === "add" && cr.new_title && <p>Новый пункт: «{cr.new_title}»</p>}
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
          <summary>{cr.action === "add" ? "Текст нового пункта" : "Предлагаемый текст"}</summary>
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
                {b.valid ? "✓" : "(не подходит, пока проверка не завершена или нет источника)"}
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
        <details>
          <summary>Написать рецензию</summary>
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
        </details>
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
            Отклонить предложение
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
  const [created, setCreated] = useState(""); // предложение создано, а основание не добавилось — не создавать дубль
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
      : `${KIND_LABEL[draft.kind]} в ${draft.parent ? `${draft.parent.number} «${draft.parent.title}»` : "всю методику"}`;
  const unchanged = draft.action === "edit" && proposed.trim() === original.trim();
  return (
    <form className="card propose" onSubmit={submit}>
      <h3 className="h3">
        {draft.action === "edit" ? "Изменить" : "Добавить"}: {where}
      </h3>
      <p className="muted">
        Методика меняется только через предложение: его принимает руководитель после одобряющей рецензии и если есть основание —
        завершённая проверка, факт или статья из банка с источником.
      </p>
      {draft.action === "add" && (
        <label className="field">
          Название нового пункта
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
        Зачем — что показали проверки или статьи
        <textarea rows={3} value={description} onChange={(ev) => setDescription(ev.target.value)} />
      </label>
      <label className="field">
        {draft.action === "edit" ? "Новый текст" : "Текст нового пункта"}
        <textarea rows={6} value={proposed} onChange={(ev) => setProposed(ev.target.value)} required />
      </label>
      <label className="field">
        Основание — проверка (можно добавить позже)
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
  openCr: (code: string) => void;
}

function NodeActions({ node, ctx }: { node: Section | null; ctx: TreeCtx }) {
  if (!ctx.canPropose) return null;
  const kinds = CHILD_KINDS[node?.kind ?? ""];
  return (
    <div className="node-actions">
      {node && (
        <button type="button" className="link-btn" onClick={() => ctx.setDraft({ action: "edit", node })}>
          Предложить правку
        </button>
      )}
      {kinds.map((k) => (
        <button key={k} type="button" className="link-btn" onClick={() => ctx.setDraft({ action: "add", parent: node, kind: k })}>
          Добавить: {KIND_LABEL[k]}
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

/** Первая фраза текста — чтобы понять, о чём пункт, не раскрывая его. */
function preview(text: string, limit = 170): string {
  const flat = text.split(/\s+/).join(" ").trim();
  const first = flat.split(/(?<=[.!?])\s/)[0] ?? "";
  return first.length > limit ? `${first.slice(0, limit).replace(/\s+\S*$/, "")}…` : first;
}

const say = (n: number, one: string, few: string, many: string) => plural(n, one, few, many);

/** Что внутри пункта: видно, не раскрывая его. */
function inside(children: Section[], all: Section[]): string {
  const count = (kind: NodeKind, list: Section[]) => list.filter((n) => n.kind === kind).length;
  const variants = count("variant", children);
  const under = children.flatMap((c) => all.filter((n) => n.parent === c.number));
  const tasks = count("task", children) + count("task", under);
  const parts = [];
  if (variants) parts.push(say(variants, "вариант", "варианта", "вариантов"));
  if (tasks) parts.push(say(tasks, "задание", "задания", "заданий"));
  return parts.join(" · ");
}

function Node({ node, ctx }: { node: Section; ctx: TreeCtx }) {
  const children = ctx.nodes.filter((n) => n.parent === node.number);
  const sections = children.filter((n) => n.kind === "section");
  const nested = children.filter((n) => n.kind !== "section");
  const work = ctx.work.get(node.number);
  const crs = ctx.openCrs.get(node.number) ?? [];
  const contents = inside(children, ctx.nodes);
  const short = node.kind === "direction" || node.kind === "variant" ? preview(node.content) : "";
  return (
    <details className={`node node-${node.kind}`}>
      <summary className="node-head">
        <span className="node-title">
          {node.title}
          {node.stability === "contested" && <span className={`badge stab-${node.stability}`}>{STABILITY_LABEL[node.stability]}</span>}
          {crs.length > 0 && <span className="badge st-review">есть предложение</span>}
        </span>
        {short && <span className="muted node-preview">{short}</span>}
        {contents && <span className="muted node-count">{contents}</span>}
      </summary>
      <div className="node-body">
        <p className="pre-line node-text">{node.content || <span className="muted">Текста пока нет.</span>}</p>
        <p className="muted node-info">
          {KIND_LABEL[node.kind]} <span className="mono">{node.number}</span> · {STABILITY_LABEL[node.stability]}
        </p>
        {(work?.hyps.length || work?.exps.length || crs.length) ? (
          <div className="node-links">
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
              <button key={c} type="button" className="link-btn mono" onClick={() => ctx.openCr(c)}>
                {c}: открытое предложение
              </button>
            ))}
          </div>
        ) : null}
        <NodeActions node={node} ctx={ctx} />
        <DraftHere node={node} ctx={ctx} />
        {sections.map((s) => (
          <Node key={s.number} node={s} ctx={ctx} />
        ))}
        {nested.map((n) => (
          <Node key={n.number} node={n} ctx={ctx} />
        ))}
      </div>
    </details>
  );
}

type MethodTab = "method" | "changes" | "history";

export function Methodology() {
  const me = useMe();
  const [draft, setDraft] = useState<Draft | null>(null);
  // ссылка вида /methodology#cr-CR-02 (из отчёта) сразу открывает предложения
  const [tab, setTab] = useState<MethodTab>(window.location.hash.startsWith("#cr-") ? "changes" : "method");
  const m = useQuery({ queryKey: ["methodology"], queryFn: getMethodology });
  const crs = useQuery({ queryKey: ["crs"], queryFn: listCrs });
  const versions = useQuery({ queryKey: ["versions"], queryFn: listVersions });
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const hyps = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const nodes = Array.isArray(m.data?.sections) ? m.data.sections : [];
  const crList = Array.isArray(crs.data) ? crs.data : [];
  const versionList = Array.isArray(versions.data) ? versions.data : [];
  const crsLoaded = crs.isSuccess;
  useEffect(() => {
    if (tab === "changes" && crsLoaded && window.location.hash.startsWith("#cr-")) {
      document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "start" });
    }
  }, [crsLoaded, tab]);
  const openCr = (code: string) => {
    window.location.hash = `cr-${code}`;
    setTab("changes");
  };
  const canPropose = me.data?.role === "researcher" || me.data?.role === "owner";
  // что относится к пункту: идеи, проверки, открытые предложения
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
  const openCount = crList.filter((c) => c.status === "proposed" || c.status === "review").length;
  const ctx: TreeCtx = { nodes, canPropose, draft, setDraft, work, openCrs, openCr };
  const common = nodes.filter((n) => !n.parent && n.kind === "section");
  const directions = nodes.filter((n) => !n.parent && n.kind !== "section");
  const tabs: Array<{ key: MethodTab; label: string }> = [
    { key: "method", label: "Как мы исследуем" },
    { key: "changes", label: `Предложения изменений${openCount ? ` · ${openCount}` : ""}` },
    { key: "history", label: "История версий" },
  ];
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">МЕТОДИКА · ВЕРСИЯ {m.data?.version ?? "…"}</span>
        <h1 className="page-title">Методика</h1>
        <p className="lead">
          Что изучает лаборатория и по каким правилам она это делает. Изменить методику можно только предложением с
          основанием, и его должен одобрить рецензент.
        </p>
      </section>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="tabs" role="tablist" aria-label="Разделы методики">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={tab === t.key ? "tab active" : "tab"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "method" && (
        <div className="tree" role="tabpanel">
          {m.isPending && <p className="muted">Загрузка…</p>}
          <p className="muted">Нажмите на пункт, чтобы прочитать его полностью.</p>
          {directions.map((d) => (
            <div key={d.number} className="card node-card">
              <Node node={d} ctx={ctx} />
            </div>
          ))}
          {common.length > 0 && (
            <section className="card node-card">
              <h2 className="h3">Правила для всей методики</h2>
              {common.map((s) => (
                <Node key={s.number} node={s} ctx={ctx} />
              ))}
            </section>
          )}
          {m.isSuccess && nodes.length === 0 && <p className="muted">Методика пока пуста.</p>}
          {canPropose && (
            <div className="method-add">
              <NodeActions node={null} ctx={ctx} />
              <DraftHere node={null} ctx={ctx} />
            </div>
          )}
          <p>
            <a className="btn-ghost" href="/api/methodology/export.docx">
              Скачать методику в Word
            </a>
          </p>
        </div>
      )}
      {tab === "changes" && (
        <section className="cr-board" role="tabpanel">
          {crs.isPending && <p className="muted">Загрузка…</p>}
          {crs.isError && (
            <p className="error" role="alert">
              {crs.error.message}
            </p>
          )}
          {crList.map((cr) => (
            <CrCard key={cr.code} cr={cr} role={me.data?.role} />
          ))}
          {crs.isSuccess && crList.length === 0 && (
            <p className="muted">Предложений пока нет. Чтобы предложить правку, откройте нужный пункт методики.</p>
          )}
        </section>
      )}
      {tab === "history" && (
        <section className="card" role="tabpanel">
          {versionList.length === 0 && <p className="muted">Версий пока нет.</p>}
          <ul className="list">
            {versionList.map((v) => (
              <li key={v.version}>
                <span className="mono">{v.version}</span> — {v.notes}{" "}
                <span className="muted">{new Date(v.created_at).toLocaleDateString("ru-RU")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
