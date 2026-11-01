import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

interface ReportSections {
  summary?: string;
  verdict?: "confirmed" | "rejected" | "inconclusive";
  verdict_reason?: string;
  interpretation?: string[];
  meaning?: string;
  methodology?: string;
  limitations?: string[];
  next?: string[];
}

interface Report {
  id: number;
  experiment: string;
  run_id: number | null;
  version: number;
  status: "draft" | "review" | "approved" | "rejected";
  sections: ReportSections;
  problems: string;
  note: string;
  reviewer: string;
  writing: boolean;
  kb_status: string;
  kb_doc_id: string;
  created_at: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...init });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

const STATUS: Record<Report["status"], string> = {
  draft: "черновик",
  review: "на рецензии",
  approved: "одобрен",
  rejected: "отклонён",
};
const BADGE: Record<Report["status"], string> = { draft: "st-planned", review: "st-review", approved: "st-done", rejected: "st-failed" };
const VERDICT = { confirmed: "гипотеза подтверждена", rejected: "гипотеза отклонена", inconclusive: "результат неоднозначен" };
const KB: Record<string, string> = {
  queued: "ждёт импорта в базу знаний",
  processing: "загружается в базу знаний",
  done: "в базе знаний",
  duplicate: "уже был в базе знаний",
  failed: "импорт в базу знаний не удался",
};
const lines = (t: string) => t.split("\n").map((x) => x.trim()).filter(Boolean);

function Editor({ r, onDone }: { r: Report; onDone: () => void }) {
  const qc = useQueryClient();
  const s = r.sections;
  const [summary, setSummary] = useState(s.summary ?? "");
  const [verdict, setVerdict] = useState(s.verdict ?? "inconclusive");
  const [reason, setReason] = useState(s.verdict_reason ?? "");
  const [interp, setInterp] = useState((s.interpretation ?? []).join("\n"));
  const [meaning, setMeaning] = useState(s.meaning ?? "");
  const [methodology, setMethodology] = useState(s.methodology ?? "");
  const [limits, setLimits] = useState((s.limitations ?? []).join("\n"));
  const [next, setNext] = useState((s.next ?? []).join("\n"));
  const m = useMutation({
    mutationFn: () =>
      call<Report>(`/reports/${r.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          sections: { summary, verdict, verdict_reason: reason, interpretation: lines(interp), meaning, methodology, limitations: lines(limits), next: lines(next) },
        }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["reports", r.experiment] });
      onDone();
    },
  });
  return (
    <div className="report-editor">
      <label className="field">
        Резюме
        <textarea rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} />
      </label>
      <div className="form-grid">
        <label className="field">
          Вердикт
          <select value={verdict} onChange={(e) => setVerdict(e.target.value as typeof verdict)}>
            {Object.entries(VERDICT).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Почему
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      </div>
      <label className="field">
        Интерпретация — пункт на строку
        <textarea rows={5} value={interp} onChange={(e) => setInterp(e.target.value)} />
      </label>
      <label className="field">
        Что это значит для задания методики
        <textarea rows={2} value={meaning} onChange={(e) => setMeaning(e.target.value)} />
      </label>
      <label className="field">
        Предложение для методики (если результат его оправдывает)
        <textarea rows={2} value={methodology} onChange={(e) => setMethodology(e.target.value)} />
      </label>
      <label className="field">
        Ограничения — пункт на строку
        <textarea rows={3} value={limits} onChange={(e) => setLimits(e.target.value)} />
      </label>
      <label className="field">
        Что дальше — пункт на строку
        <textarea rows={3} value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="review-form">
        <button type="button" className="btn-primary" disabled={m.isPending} onClick={() => m.mutate()}>
          Сохранить
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Отмена
        </button>
      </div>
    </div>
  );
}

function ReportCard({ r, role }: { r: Report; role: string | undefined }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["reports", r.experiment] });
  const act = useMutation({
    mutationFn: (a: "submit" | "approve" | "reject") =>
      call<Report>(`/reports/${r.id}/${a}`, { method: "POST", ...(a === "reject" ? { body: JSON.stringify({ note }) } : {}) }),
    onSuccess: refresh,
  });
  const canEdit = (role === "researcher" || role === "owner") && (r.status === "draft" || r.status === "review");
  const canReview = (role === "reviewer" || role === "owner") && r.status === "review";
  const s = r.sections;
  return (
    <article className="card report">
      <div className="kb-meta">
        <strong>Отчёт v{r.version}</strong>
        <span className={`badge ${BADGE[r.status]}`}>{STATUS[r.status]}</span>
        {s.verdict && <span className="badge st-running">{VERDICT[s.verdict]}</span>}
        {r.run_id && (
          <Link to={`/run/${r.run_id}`} className="muted">
            по запуску №{r.run_id}
          </Link>
        )}
        {r.reviewer && <span className="muted">рецензент {r.reviewer}</span>}
        {r.kb_status && (
          <span className="muted">
            ·{" "}
            {r.kb_status === "done" && r.kb_doc_id ? (
              <Link to={`/knowledge/article/${encodeURIComponent(r.kb_doc_id)}`}>{KB.done}</Link>
            ) : (
              KB[r.kb_status] ?? r.kb_status
            )}
          </span>
        )}
      </div>
      {r.writing && <p className="muted">Qwen пишет текст отчёта по фактам расчёта — несколько минут.</p>}
      {r.problems && <p className="blockers">{r.problems}</p>}
      {r.note && <p className="muted">Рецензент: {r.note}</p>}
      {!r.writing && !editing && s.summary && (
        <>
          <p>{s.summary}</p>
          {s.verdict_reason && <p className="muted">Вердикт: {s.verdict_reason}</p>}
          <details>
            <summary>Интерпретация, ограничения, что дальше</summary>
            {(s.interpretation ?? []).length > 0 && (
              <ul className="list">
                {s.interpretation?.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            )}
            {s.meaning && <p>Для задания методики: {s.meaning}</p>}
            {s.methodology && <p>Предложение для методики: {s.methodology}</p>}
            {(s.limitations ?? []).length > 0 && <p className="muted">Ограничения: {s.limitations?.join("; ")}</p>}
            {(s.next ?? []).length > 0 && <p className="muted">Что дальше: {s.next?.join("; ")}</p>}
          </details>
        </>
      )}
      {editing && <Editor r={r} onDone={() => setEditing(false)} />}
      {!r.writing && s.summary && !editing && (
        <div className="review-form">
          <a className="btn-ghost" href={`/api/reports/${r.id}/export.docx`}>
            Скачать Word
          </a>
          <a className="btn-ghost" href={`/api/reports/${r.id}/export.pdf`}>
            Скачать PDF
          </a>
          {canEdit && (
            <button type="button" className="btn-ghost" onClick={() => setEditing(true)}>
              Править текст
            </button>
          )}
          {canEdit && r.status === "draft" && (
            <button type="button" className="btn-primary" disabled={act.isPending} onClick={() => act.mutate("submit")}>
              На рецензию
            </button>
          )}
          {canReview && (
            <button type="button" className="btn-primary" disabled={act.isPending} onClick={() => act.mutate("approve")}>
              Одобрить и отправить в базу знаний
            </button>
          )}
        </div>
      )}
      {canReview && !editing && (
        <div className="review-form">
          <label className="field inline grow">
            Почему отклоняете
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="button" className="btn-ghost" disabled={act.isPending || note.trim().length < 3} onClick={() => act.mutate("reject")}>
            Отклонить
          </button>
        </div>
      )}
      {act.isError && (
        <p className="error" role="alert">
          {act.error.message}
        </p>
      )}
    </article>
  );
}

/** Отчёты Qwen по эксперименту: текст по фактам расчёта, рецензия, Word/PDF, база знаний. */
export function ReportPanel({ code, role }: { code: string; role: string | undefined }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["reports", code],
    queryFn: () => call<Report[]>(`/experiments/${code}/reports`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((r) => r.writing || r.kb_status === "queued" || r.kb_status === "processing") ? 15_000 : false,
  });
  const make = useMutation({
    mutationFn: () => call<Report>(`/experiments/${code}/reports`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports", code] }),
  });
  const reports = q.data ?? [];
  const canMake = role === "researcher" || role === "owner";
  return (
    <section className="card">
      <div className="viz-head">
        <h2 className="h2">Отчёт</h2>
        {canMake && (
          <button type="button" className="btn-ghost" disabled={make.isPending} onClick={() => make.mutate()}>
            {reports.length ? "Новая версия отчёта" : "Сформировать отчёт"}
          </button>
        )}
      </div>
      <p className="muted">
        Отчёт пишет Qwen по фактам последнего удачного запуска: цифры, таблицы и графики — из расчёта, текст —
        интерпретация модели (числа в нём сверяются с расчётом). После одобрения рецензентом отчёт попадает в базу
        знаний, в ветку «Отчёты экспериментов».
      </p>
      {make.isError && <p className="error">{make.error.message}</p>}
      {q.isSuccess && reports.length === 0 && <p className="muted">Отчётов ещё нет — он появится сам после удачного запуска.</p>}
      {reports.map((r) => (
        <ReportCard key={r.id} r={r} role={role} />
      ))}
    </section>
  );
}
