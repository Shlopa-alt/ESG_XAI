import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { listExperiments } from "../api/experiments";
import type { KbRefIn } from "../api/hypotheses";
import { kbArticle } from "../api/kb";
import { listCrs } from "../api/methodology";
import { useMe } from "../auth/useAuth";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || data === null) {
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d : `Ошибка ${res.status}`);
  }
  return data;
}

const RELATIONS = [
  { value: "replicates", label: "воспроизводит статью" },
  { value: "tests", label: "проверяет утверждение статьи" },
  { value: "uses_method", label: "использует метод статьи" },
  { value: "motivated_by", label: "опирается на статью" },
];

/** Привязка статьи к эксперименту и к CR — для researcher и owner. */
function LinkPanel({ refIn }: { refIn: KbRefIn }) {
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const crs = useQuery({ queryKey: ["crs"], queryFn: listCrs });
  const [exp, setExp] = useState("");
  const [relation, setRelation] = useState("replicates");
  const [cr, setCr] = useState("");
  const qc = useQueryClient();
  const link = useMutation({
    mutationFn: () => post(`/experiments/${exp}/links`, { ...refIn, relation }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["experiment", exp] });
      void qc.invalidateQueries({ queryKey: ["experiment-links"] });
    },
  });
  const basis = useMutation({
    mutationFn: () => post(`/change-requests/${cr}/bases`, { basis_type: "kb_article", ...refIn }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["crs"] }),
  });
  const expList = Array.isArray(exps.data) ? exps.data : [];
  const openCrs = (Array.isArray(crs.data) ? crs.data : []).filter((c) => c.status === "proposed" || c.status === "review");
  return (
    <section className="card">
      <h2 className="h2">Связать с экспериментом или изменением методологии</h2>
      <div className="review-form">
        <label className="field inline grow">
          Эксперимент
          <select value={exp} onChange={(e) => setExp(e.target.value)}>
            <option value="">— выберите —</option>
            {expList.map((e) => (
              <option key={e.code} value={e.code}>
                {e.code} · {e.title.slice(0, 60)}
              </option>
            ))}
          </select>
        </label>
        <label className="field inline">
          Как связан
          <select value={relation} onChange={(e) => setRelation(e.target.value)}>
            {RELATIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn-ghost" disabled={!exp || link.isPending} onClick={() => link.mutate()}>
          Привязать
        </button>
      </div>
      {link.isSuccess && (
        <p role="status">
          Привязано к <Link to={`/experiments/${exp}`}>{exp}</Link>.
        </p>
      )}
      <div className="review-form">
        <label className="field inline grow">
          Основание для CR
          <select value={cr} onChange={(e) => setCr(e.target.value)}>
            <option value="">— выберите открытый CR —</option>
            {openCrs.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} · {c.title.slice(0, 60)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn-ghost" disabled={!cr || basis.isPending} onClick={() => basis.mutate()}>
          Добавить основание
        </button>
      </div>
      {!refIn.doi && (
        <p className="muted">У статьи нет DOI — основанием CR она засчитана не будет («требует источника»).</p>
      )}
      {basis.isSuccess && (
        <p role="status">
          Добавлено к <Link to="/methodology">{cr}</Link>.
        </p>
      )}
      {(link.error ?? basis.error) && (
        <p className="error" role="alert">
          {(link.error ?? basis.error)?.message}
        </p>
      )}
    </section>
  );
}

export function Article() {
  const { docId = "" } = useParams();
  const navigate = useNavigate();
  const me = useMe();
  const q = useInfiniteQuery({
    queryKey: ["kb", "article", docId],
    queryFn: ({ pageParam }) => kbArticle(docId, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
  });
  if (q.isPending) return <p className="muted">Загрузка…</p>;
  if (q.isError) {
    return (
      <p className="error" role="alert">
        {q.error.message}
      </p>
    );
  }
  const a = q.data.pages[0];
  if (!a) return null;
  const fragments = q.data.pages.flatMap((p) => p.fragments ?? []);
  const doi = a.doi ?? a.url?.match(/10\.\d{4,9}\/\S+/)?.[0] ?? "";
  const refIn: KbRefIn = { kind: "article", kbrag_id: a.doc_id, kb_path: a.kbs[0] ?? "", title: a.title ?? "", doi };
  const canLink = me.data?.role === "researcher" || me.data?.role === "owner";
  return (
    <>
      <div className="muted">
        <Link to="/knowledge">База знаний</Link> / статья
      </div>
      <section className="page-head">
        <span className="eyebrow">
          {a.year ?? "—"} · {a.kbs.join(", ")}
        </span>
        <h1 className="page-title article-title">{a.title || a.doc_id}</h1>
        {a.authors && a.authors.length > 0 && <p className="lead">{a.authors.join(", ")}</p>}
        <p className="muted">
          {a.journal && <>{a.journal} · </>}
          {a.pages ? `${a.pages} с. · ` : ""}
          {a.fragments_total ?? a.chunks} фрагментов
          {doi && (
            <>
              {" "}
              ·{" "}
              <a href={`https://doi.org/${doi}`} target="_blank" rel="noreferrer">
                DOI {doi}
              </a>
            </>
          )}
          {!doi && a.url && (
            <>
              {" "}
              ·{" "}
              <a href={a.url} target="_blank" rel="noreferrer">
                источник
              </a>
            </>
          )}
        </p>
        <div className="review-form">
          <button type="button" className="btn-primary" onClick={() => navigate("/hypotheses", { state: { ref: refIn } })}>
            Предложить гипотезу по этой статье
          </button>
        </div>
      </section>
      {canLink && <LinkPanel refIn={refIn} />}
      <section className="card">
        <h2 className="h2">Текст по фрагментам</h2>
        <ol className="fragments">
          {fragments.map((f) => (
            <li key={f.ord}>
              {f.headings.length > 0 && <div className="muted">{f.headings.join(" › ")}</div>}
              <p>{f.text}</p>
              {f.pages.length > 0 && <div className="muted mono">с. {f.pages.join(", ")}</div>}
            </li>
          ))}
        </ol>
        {q.hasNextPage && (
          <button type="button" className="btn-ghost" onClick={() => void q.fetchNextPage()} disabled={q.isFetchingNextPage}>
            Показать ещё
          </button>
        )}
      </section>
    </>
  );
}
