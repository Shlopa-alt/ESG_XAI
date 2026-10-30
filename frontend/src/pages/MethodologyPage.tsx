import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  type ChangeRequest,
  CR_STATUS_LABEL,
  getMethodology,
  listCrs,
  listVersions,
  reviewCr,
  setCrStatus,
  STABILITY_LABEL,
} from "../api/methodology";
import { useMe } from "../auth/useAuth";

const VERDICTS = { approve: "одобрено", changes: "нужны правки", reject: "отклонено" } as const;
const CR_BADGE = { proposed: "st-planned", review: "st-review", accepted: "st-done", rejected: "st-planned" } as const;

function CrCard({ cr, role }: { cr: ChangeRequest; role: string | undefined }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["crs"] });
    void qc.invalidateQueries({ queryKey: ["methodology"] });
    void qc.invalidateQueries({ queryKey: ["versions"] });
  };
  const review = useMutation({ mutationFn: (v: string) => reviewCr(cr.code, v, text), onSuccess: refresh });
  const decide = useMutation({
    mutationFn: (s: "accepted" | "rejected") => setCrStatus(cr.code, s),
    onSuccess: refresh,
  });
  const open = cr.status === "proposed" || cr.status === "review";
  const error = review.error ?? decide.error;
  return (
    <article className="card cr">
      <div className="kb-meta">
        <span className="mono">{cr.code}</span> · раздел {cr.section}
        <span className={`badge ${CR_BADGE[cr.status]}`}>{CR_STATUS_LABEL[cr.status]}</span>
        {cr.target_version && <span className="muted">→ версия {cr.target_version}</span>}
      </div>
      <h3 className="h3">{cr.title}</h3>
      {cr.description && <p className="muted">{cr.description}</p>}
      {cr.proposed_content && (
        <details>
          <summary>Предлагаемый текст раздела</summary>
          <p>{cr.proposed_content}</p>
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
      {open && cr.blockers.length > 0 && (
        <p className="blockers">Принять нельзя: {cr.blockers.join("; ")}.</p>
      )}
      {open && (role === "reviewer" || role === "owner") && (
        <div className="review-form">
          <label className="field inline grow">
            Комментарий рецензента
            <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="button" className="btn-ghost" onClick={() => review.mutate("approve")}>
            Одобрить
          </button>
          <button type="button" className="btn-ghost" onClick={() => review.mutate("changes")}>
            Нужны правки
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
          <button type="button" className="btn-ghost" onClick={() => decide.mutate("rejected")}>
            Отклонить
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

export function Methodology() {
  const me = useMe();
  const m = useQuery({ queryKey: ["methodology"], queryFn: getMethodology });
  const crs = useQuery({ queryKey: ["crs"], queryFn: listCrs });
  const versions = useQuery({ queryKey: ["versions"], queryFn: listVersions });
  // Ответ может прийти не тем, что ждём (сервер старой версии), — страница не падает
  const sections = Array.isArray(m.data?.sections) ? m.data.sections : [];
  const crList = Array.isArray(crs.data) ? crs.data : [];
  const versionList = Array.isArray(versions.data) ? versions.data : [];
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">МЕТОДОЛОГИЯ · ВЕРСИЯ {m.data?.version ?? "…"}</span>
        <h1 className="page-title">Методология</h1>
        <p className="lead">
          Разделы по постановке задачи лаборатории для ИНС. Раздел меняется только через предложение изменения (CR):
          нужно основание — завершённый эксперимент, факт или статья базы знаний — и одобряющая рецензия.
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
      <div className="grid-2">
        <section className="card">
          <h2 className="h2">Разделы</h2>
          <ol className="list">
            {sections.map((s) => (
              <li key={s.number}>
                <strong>{s.title}</strong>{" "}
                <span className={`badge stab-${s.stability}`}>{STABILITY_LABEL[s.stability]}</span>
                <p className="muted">{s.content}</p>
              </li>
            ))}
          </ol>
        </section>
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
