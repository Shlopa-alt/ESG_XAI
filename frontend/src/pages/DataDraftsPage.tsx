import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type KeyboardEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  approveDraft,
  type Cell,
  commandDraft,
  type Draft,
  DRAFT_BADGE,
  DRAFT_STATUS,
  type DraftOp,
  type DraftStatus,
  editDraft,
  getDraft,
  JOB_STATUS,
  listDrafts,
  rejectDraft,
  scanTables,
} from "../api/dataDrafts";
import { useMe } from "../auth/useAuth";

const FILTERS: Array<[DraftStatus | "all", string]> = [
  ["proposed", "Ждут решения"],
  ["approved", "Датасет создан"],
  ["rejected", "Отклонены"],
  ["all", "Все"],
];
const SHOWN = 100;

const show = (v: Cell) => (v === null ? "" : typeof v === "number" ? v.toLocaleString("ru-RU", { maximumFractionDigits: 6 }) : v);
const day = (iso: string) => new Date(iso).toLocaleDateString("ru-RU");

function useCanEdit(): boolean {
  const me = useMe();
  return me.data?.role === "researcher" || me.data?.role === "owner";
}

export function DataDrafts() {
  const [filter, setFilter] = useState<DraftStatus | "all">("proposed");
  const canEdit = useCanEdit();
  const q = useQuery({ queryKey: ["data-drafts", filter], queryFn: () => listDrafts(filter) });
  const scan = useMutation({ mutationFn: () => scanTables() });
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">
          <Link to="/knowledge">БАЗА ЗНАНИЙ</Link> · ДАННЫЕ ИЗ СТАТЕЙ
        </span>
        <h1 className="page-title">Черновики данных</h1>
        <p className="muted">
          Таблицы-наблюдения из статей базы знаний: их нашёл и разобрал обработчик, отобрала и описала Qwen. Проверьте
          таблицу, поправьте руками или командой Qwen — и создайте датасет, на котором можно запустить метод
          лаборатории.
        </p>
        {canEdit && (
          <div className="run-head">
            <button type="button" className="btn-ghost" disabled={scan.isPending || scan.isSuccess} onClick={() => scan.mutate()}>
              Поискать таблицы во всех статьях
            </button>
            {scan.isSuccess && <span className="muted">Задача Qwen №{scan.data.job} в очереди — черновики появятся здесь.</span>}
            {scan.isError && <span className="error" role="alert">{scan.error.message}</span>}
          </div>
        )}
      </section>
      <div className="filters" role="group" aria-label="Статус черновика">
        {FILTERS.map(([key, label]) => (
          <button key={key} type="button" className={filter === key ? "chip active" : "chip"} aria-pressed={filter === key}
            onClick={() => setFilter(key)}>
            {label}
          </button>
        ))}
      </div>
      <section className="card">
        {q.isError && <p className="error" role="alert">{q.error.message}</p>}
        {q.data && q.data.length === 0 && <p className="muted">Черновиков нет.</p>}
        {q.data && q.data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Черновик</th>
                  <th>Статья</th>
                  <th className="num">Строк × столбцов</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <Link to={`/data-drafts/${d.id}`}>{d.title || `Таблица ${d.table_number}`}</Link>
                    </td>
                    <td>
                      {d.article_title || d.doc_id}
                      <div className="muted">
                        таблица {d.table_number}
                        {d.page ? `, с. ${d.page}` : ""}
                      </div>
                    </td>
                    <td className="num mono">
                      {d.n_rows} × {d.n_cols}
                    </td>
                    <td>
                      <span className={`badge ${DRAFT_BADGE[d.status]}`}>{DRAFT_STATUS[d.status]}</span>
                      {d.dataset && (
                        <div>
                          <Link className="mono" to={`/datasets/${d.dataset}`}>{d.dataset}</Link>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

type Editing = { kind: "cell"; row: number; col: number; value: string } | { kind: "head"; col: number; value: string };

// поле правки появляется по нажатию — фокус сразу в нём, чтобы печатать без лишнего щелчка
const focus = (el: HTMLInputElement | null) => el?.focus();

function DraftTable({ d, canEdit, apply, pending }: { d: Draft; canEdit: boolean; apply: (ops: DraftOp[]) => void; pending: boolean }) {
  const [all, setAll] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const rows = all ? d.rows : d.rows.slice(0, SHOWN);
  const save = () => {
    if (!editing) return;
    const column = d.columns[editing.col] ?? "";
    if (editing.kind === "cell") {
      const before = show(d.rows[editing.row]?.[editing.col] ?? null);
      if (editing.value !== before) apply([{ op: "set_cell", row: editing.row, column, value: editing.value }]);
    } else if (editing.value.trim() && editing.value.trim() !== column) {
      apply([{ op: "rename", column, to: editing.value.trim() }]);
    }
    setEditing(null);
  };
  const keys = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") setEditing(null);
  };
  return (
    <section className="card">
      <h2 className="h2">
        Таблица · <span className="mono">{d.rows.length} × {d.columns.length}</span>
      </h2>
      {canEdit && (
        <p className="muted">
          Нажмите на ячейку или имя столбца, чтобы поправить (Enter — сохранить, Esc — отмена). Каждая правка
          попадает в журнал и в описание будущего датасета.
        </p>
      )}
      <div className="table-wrap">
        <table className="table draft-table">
          <thead>
            <tr>
              <th scope="col">№</th>
              {d.columns.map((c, j) => (
                <th key={c} scope="col">
                  {editing?.kind === "head" && editing.col === j ? (
                    <input aria-label={`Новое имя столбца «${c}»`} value={editing.value} ref={focus}
                      onChange={(e) => setEditing({ ...editing, value: e.target.value })} onKeyDown={keys} onBlur={save} />
                  ) : canEdit ? (
                    <button type="button" className="link-btn" disabled={pending} onClick={() => setEditing({ kind: "head", col: j, value: c })}>
                      {c}
                    </button>
                  ) : (
                    c
                  )}
                  <div className="draft-col-meta">
                    {d.numeric.includes(c) ? <span className="muted">число</span> : <span className="muted">текст</span>}
                    {canEdit && !d.numeric.includes(c) && (
                      <button type="button" className="link-btn" disabled={pending} onClick={() => apply([{ op: "to_number", column: c }])}>
                        в числа
                      </button>
                    )}
                    {canEdit && d.columns.length > 1 && (
                      <button type="button" className="link-btn" aria-label={`Убрать столбец «${c}»`} disabled={pending}
                        onClick={() => apply([{ op: "drop_columns", columns: [c] }])}>
                        убрать
                      </button>
                    )}
                  </div>
                </th>
              ))}
              {canEdit && <th scope="col"><span className="sr-only">Действия</span></th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="mono muted">{i + 1}</td>
                {r.map((v, j) => (
                  <td key={j} className={typeof v === "number" ? "num mono" : undefined}>
                    {editing?.kind === "cell" && editing.row === i && editing.col === j ? (
                      <input aria-label={`Строка ${i + 1}, «${d.columns[j]}»`} value={editing.value} ref={focus}
                        onChange={(e) => setEditing({ ...editing, value: e.target.value })} onKeyDown={keys} onBlur={save} />
                    ) : canEdit ? (
                      <button type="button" className="cell-btn" disabled={pending}
                        aria-label={`Править: строка ${i + 1}, «${d.columns[j]}»`}
                        onClick={() => setEditing({ kind: "cell", row: i, col: j, value: show(v) })}>
                        {show(v) || <span className="muted">—</span>}
                      </button>
                    ) : (
                      show(v)
                    )}
                  </td>
                ))}
                {canEdit && (
                  <td>
                    <button type="button" className="link-btn" aria-label={`Убрать строку ${i + 1}`} disabled={pending}
                      onClick={() => apply([{ op: "drop_rows", rows: [i] }])}>
                      убрать
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.rows.length > SHOWN && (
        <button type="button" className="btn-ghost" onClick={() => setAll(!all)}>
          {all ? `Показать первые ${SHOWN}` : `Показать все ${d.rows.length} строк`}
        </button>
      )}
    </section>
  );
}

function QwenCommand({ d }: { d: Draft }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const m = useMutation({
    mutationFn: () => commandDraft(d.id, text),
    onSuccess: (data) => {
      qc.setQueryData(["data-draft", d.id], data);
      setText("");
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  const busy = d.jobs.some((j) => j.status === "queued" || j.status === "running");
  return (
    <section className="card">
      <h2 className="h2">Команда Qwen</h2>
      <p className="muted">
        Скажите словами, что поправить: «убери итоговые строки», «переведи тыс. руб. в рубли», «переименуй столбцы
        по-русски», «оставь только 2020–2022». Qwen ответит операциями правки, платформа применит их и запишет в
        журнал; код модель не пишет.
      </p>
      <form className="review-form" onSubmit={submit}>
        <label className="field grow">
          Что сделать с таблицей
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} required minLength={3} maxLength={1000} />
        </label>
        <button type="submit" className="btn-primary" disabled={m.isPending || busy}>
          {busy ? "Qwen работает…" : "Отправить"}
        </button>
      </form>
      {m.isError && <p className="error" role="alert">{m.error.message}</p>}
      {d.jobs.length > 0 && (
        <ul className="list draft-jobs">
          {d.jobs.map((j) => (
            <li key={j.id}>
              «{j.command}» — <span className={j.status === "failed" ? "error" : "muted"}>{JOB_STATUS[j.status]}</span>
              {j.message && <p className="muted">{j.message}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Decide({ d }: { d: Draft }) {
  const qc = useQueryClient();
  const me = useMe();
  const [title, setTitle] = useState(d.title);
  const [nda, setNda] = useState(false);
  const [note, setNote] = useState("");
  const done = (data: Draft) => {
    qc.setQueryData(["data-draft", d.id], data);
    void qc.invalidateQueries({ queryKey: ["data-drafts"] });
  };
  const approve = useMutation({
    mutationFn: () => approveDraft(d.id, { title, description: d.description, access_level: nda ? "nda" : "public" }),
    onSuccess: done,
  });
  const reject = useMutation({ mutationFn: () => rejectDraft(d.id, note), onSuccess: done });
  return (
    <section className="card accent">
      <h2 className="h2">Решение</h2>
      <form className="review-form" onSubmit={(e) => { e.preventDefault(); approve.mutate(); }}>
        <label className="field grow">
          Название датасета
          <input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} maxLength={512} />
        </label>
        {me.data?.role === "owner" && (
          <label className="check">
            <input type="checkbox" checked={nda} onChange={(e) => setNda(e.target.checked)} /> под NDA
          </label>
        )}
        <button type="submit" className="btn-primary" disabled={approve.isPending}>
          Создать датасет
        </button>
      </form>
      <p className="muted">
        Будет заведён датасет со ссылкой на статью (DOI) и срез CSV из этой таблицы; в описание войдут подпись
        таблицы и журнал правок.
      </p>
      {approve.isError && <p className="error" role="alert">{approve.error.message}</p>}
      <form className="review-form" onSubmit={(e) => { e.preventDefault(); reject.mutate(); }}>
        <label className="field grow">
          Почему отклонить
          <input value={note} onChange={(e) => setNote(e.target.value)} required minLength={3}
            placeholder="Например: это результаты регрессии, а не наблюдения" />
        </label>
        <button type="submit" className="btn-ghost" disabled={reject.isPending}>
          Отклонить
        </button>
      </form>
      {reject.isError && <p className="error" role="alert">{reject.error.message}</p>}
    </section>
  );
}

function About({ d, canEdit }: { d: Draft; canEdit: boolean }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(d.title);
  const [description, setDescription] = useState(d.description);
  const m = useMutation({
    mutationFn: () => editDraft(d.id, { title, description }),
    onSuccess: (data) => {
      qc.setQueryData(["data-draft", d.id], data);
      setEditing(false);
    },
  });
  if (editing) {
    return (
      <form className="card" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <label className="field">
          Название
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={512} />
        </label>
        <label className="field">
          Описание: что такое строка, что значат столбцы, единицы
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} maxLength={4000} />
        </label>
        {m.isError && <p className="error" role="alert">{m.error.message}</p>}
        <div className="review-form">
          <button type="submit" className="btn-primary" disabled={m.isPending}>Сохранить</button>
          <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>Отмена</button>
        </div>
      </form>
    );
  }
  return (
    <section className="card">
      <p>{d.description || <span className="muted">Описания нет.</span>}</p>
      <dl className="dl">
        <dt>Статья</dt>
        <dd>
          <Link to={`/knowledge/article/${encodeURIComponent(d.doc_id)}`}>{d.article_title || d.doc_id}</Link>
          {d.doi && <span className="mono"> · DOI {d.doi}</span>}
        </dd>
        <dt>Таблица</dt>
        <dd>
          {d.table_number}
          {d.page ? `, с. ${d.page}` : ""}
          {d.caption && <span className="muted"> — {d.caption}</span>}
        </dd>
        <dt>Найдена</dt>
        <dd>{day(d.created_at)}</dd>
      </dl>
      {canEdit && (
        <button type="button" className="btn-ghost" onClick={() => setEditing(true)}>
          Править название и описание
        </button>
      )}
    </section>
  );
}

export function DataDraftPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const canEditRole = useCanEdit();
  const q = useQuery({
    queryKey: ["data-draft", id],
    queryFn: () => getDraft(id),
    // пока Qwen выполняет команду — обновлять, чтобы правка появилась сама
    refetchInterval: (query) => (query.state.data?.jobs.some((j) => j.status === "queued" || j.status === "running") ? 4000 : false),
  });
  const apply = useMutation({
    mutationFn: (ops: DraftOp[]) => editDraft(id, { ops }),
    onSuccess: (data) => qc.setQueryData(["data-draft", id], data),
  });
  if (q.isError) return <p className="error" role="alert">{q.error.message}</p>;
  const d = q.data;
  if (!d) return <p className="muted">Загрузка…</p>;
  const canEdit = canEditRole && d.status === "proposed";
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">
          <Link to="/data-drafts">ЧЕРНОВИКИ ДАННЫХ</Link> · ТАБЛИЦА {d.table_number}
        </span>
        <h1 className="page-title">{d.title || `Таблица ${d.table_number}`}</h1>
        <div className="run-head">
          <span className={`badge ${DRAFT_BADGE[d.status]}`}>{DRAFT_STATUS[d.status]}</span>
          {d.dataset && (
            <Link className="mono" to={`/datasets/${d.dataset}`}>
              {d.dataset}
            </Link>
          )}
          {d.status === "rejected" && d.note && <span className="muted">— {d.note}</span>}
        </div>
      </section>
      <About key={`${d.title}|${d.description}`} d={d} canEdit={canEdit} />
      {apply.isError && <p className="error" role="alert">{apply.error.message}</p>}
      <DraftTable d={d} canEdit={canEdit} apply={(ops) => apply.mutate(ops)} pending={apply.isPending} />
      {canEdit && <QwenCommand d={d} />}
      {canEdit && <Decide d={d} />}
      <section className="card">
        <h2 className="h2">Журнал</h2>
        <ol className="list">
          {d.history.map((h, i) => (
            <li key={i}>
              <span className="muted">
                {new Date(h.at).toLocaleString("ru-RU")} · {h.who}:
              </span>{" "}
              {h.text}
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
