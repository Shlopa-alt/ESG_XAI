import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { enableMethod, getLibrary, getMethod, type LibraryMethod, rejectMethod } from "../api/methods";
import { useMe } from "../auth/useAuth";
import { NetsTabs } from "../components/SectionTabs";

const STATUS: Record<LibraryMethod["status"], { label: string; badge: string }> = {
  ready: { label: "проверен, ждёт администратора", badge: "st-review" },
  failed: { label: "не прошёл проверку", badge: "st-failed" },
  enabled: { label: "в библиотеке", badge: "st-done" },
  rejected: { label: "отклонён", badge: "st-planned" },
};

/** Код метода и журнал проверки — по запросу: администратор читает код перед включением. */
function Code({ code }: { code: string }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["method", code], queryFn: () => getMethod(code), enabled: open });
  return (
    <details onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Код метода</summary>
      {q.isPending && open && <p className="muted">Загрузка…</p>}
      {q.data && <pre className="method-code">{q.data.script}</pre>}
    </details>
  );
}

function MethodCard({ m, isOwner }: { m: LibraryMethod; isOwner: boolean }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const done = () => void qc.invalidateQueries({ queryKey: ["methods"] });
  const enable = useMutation({ mutationFn: () => enableMethod(m.code), onSuccess: done });
  const reject = useMutation({ mutationFn: () => rejectMethod(m.code, note), onSuccess: done });
  const st = STATUS[m.status];
  const error = enable.error ?? reject.error;
  return (
    <article className="card cr" aria-label={`${m.code} ${m.title}`}>
      <div className="kb-meta">
        <span className="mono">{m.code}</span>
        <span className={`badge ${st.badge}`}>{st.label}</span>
        {m.net_title && <span className="muted">· {m.net_title}</span>}
      </div>
      <h3 className="h3">{m.title}</h3>
      {m.description && <p>{m.description}</p>}
      <p className="muted">
        Из статьи{" "}
        {m.doc_id ? <Link to={`/knowledge/article/${encodeURIComponent(m.doc_id)}`}>{m.article_title || m.doc_id}</Link> : "—"}
        {m.doi && <span className="mono"> · DOI {m.doi}</span>}
        {m.evidence && (
          <>
            : <q>{m.evidence}</q>
          </>
        )}
      </p>
      {m.params.length > 0 && (
        <p className="muted">
          Гиперпараметры авторов: {m.params.map((p) => `${p.label || p.name} = ${p.default}`).join(", ")}
        </p>
      )}
      {m.decision_note && <p>Решение{m.decided_by ? ` (${m.decided_by})` : ""}: {m.decision_note}</p>}
      <details open={m.status === "failed"}>
        <summary>Как проверяли</summary>
        <pre className="method-log">{m.check_log || "—"}</pre>
      </details>
      <Code code={m.code} />
      {isOwner && m.status === "ready" && (
        <div className="review-form">
          <label className="field inline grow">
            Комментарий (обязателен при отклонении)
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="button" className="btn-primary" disabled={enable.isPending} onClick={() => enable.mutate()}>
            Код прочитан — включить
          </button>
          <button type="button" className="btn-ghost" disabled={reject.isPending || !note.trim()} onClick={() => reject.mutate()}>
            Отклонить
          </button>
        </div>
      )}
      {isOwner && m.status === "enabled" && (
        <details>
          <summary>Убрать из библиотеки</summary>
          <div className="review-form">
            <label className="field inline grow">
              Почему
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <button type="button" className="btn-ghost" disabled={reject.isPending || !note.trim()} onClick={() => reject.mutate()}>
              Убрать
            </button>
          </div>
        </details>
      )}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
    </article>
  );
}

export function MethodLibrary() {
  const me = useMe();
  const isOwner = me.data?.role === "owner";
  const q = useQuery({ queryKey: ["methods"], queryFn: getLibrary, refetchInterval: (s) => ((s.state.data?.pending.length ?? 0) > 0 ? 15_000 : false) });
  const lib = q.data;
  const active = (lib?.methods ?? []).filter((m) => m.status === "enabled" || m.status === "ready");
  const archived = (lib?.methods ?? []).filter((m) => m.status === "failed" || m.status === "rejected");
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">НЕЙРОСЕТИ</span>
        <h1 className="page-title">Библиотека методов</h1>
        <p className="lead">
          Методы, которыми считает платформа. Новые берутся из статей банка: на странице статьи нажмите «Сделать метод по
          статье» — ИИ-помощник прочитает, какой моделью пользовались авторы, и напишет её код. Платформа проверит код и
          пробно запустит его без доступа к сети, администратор прочитает код и включит метод.
        </p>
      </section>
      <NetsTabs />
      {q.isError && (
        <p className="error" role="alert">
          {q.error.message}
        </p>
      )}
      {lib && lib.pending.length > 0 && (
        <section className="card" aria-label="Методы в работе">
          <h2 className="h2">ИИ-помощник пишет</h2>
          <ul className="list">
            {lib.pending.map((p) => (
              <li key={p.job}>
                Метод по статье{" "}
                <Link to={`/knowledge/article/${encodeURIComponent(p.doc_id)}`} className="mono">
                  {p.doc_id}
                </Link>{" "}
                — {p.status === "running" ? "пишет и проверяет" : "в очереди"} (задача № {p.job})
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="overview-block" aria-labelledby="lib-articles">
        <h2 className="section-title" id="lib-articles">
          Методы из статей
        </h2>
        {lib && active.length === 0 && (
          <p className="muted">
            Пока нет. Откройте статью в <Link to="/knowledge">банке статей</Link> и нажмите «Сделать метод по статье».
          </p>
        )}
        <div className="cr-board">
          {active.map((m) => (
            <MethodCard key={m.code} m={m} isOwner={isOwner} />
          ))}
        </div>
        {archived.length > 0 && (
          // неудачные попытки и отклонённые — история, а не рабочие методы: свёрнуты, но видны
          <details className="card details-card">
            <summary>Не прошли проверку или отклонены · {archived.length}</summary>
            <div className="cr-board">
              {archived.map((m) => (
                <MethodCard key={m.code} m={m} isOwner={isOwner} />
              ))}
            </div>
          </details>
        )}
      </section>
      <section className="overview-block" aria-labelledby="lib-builtin">
        <h2 className="section-title" id="lib-builtin">
          Встроенные методы
        </h2>
        <ul className="list card">
          {lib?.builtin.map((b) => (
            <li key={b.key}>
              <strong>{b.title}</strong>
              <span className="muted"> — {b.description}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
