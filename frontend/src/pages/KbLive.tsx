import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import type { KbRefIn } from "../api/hypotheses";
import { type KbHit, kbDocumentsPage, kbSearch, kbStats, kbTree } from "../api/kb";
import { plural } from "../components/Ux";

/** Ссылка на найденный фрагмент — источник идеи, проверки, предложения. */
export function refFromHit(h: KbHit, kb: string): KbRefIn {
  const doi = h.url?.match(/10\.\d{4,9}\/\S+/)?.[0] ?? "";
  return { kind: "article", kbrag_id: h.doc_id, kb_path: kb, title: h.title, doi, quote: h.text.slice(0, 400), page: h.pages[0] ?? null };
}

const ROOT = "esg";
const PAGE = 25;
const fmt = (n: number | undefined) => (n ?? 0).toLocaleString("ru-RU");

/** Поиск, темы и полный список статей банка — живые данные из KBRAG. */
export function KbLive() {
  const [kb, setKb] = useState(ROOT);
  // Запрос живёт в адресе (?q=): сюда ведёт и поиск из шапки
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const navigate = useNavigate();
  const [titleDraft, setTitleDraft] = useState("");
  const [title, setTitle] = useState("");
  const [limit, setLimit] = useState(PAGE);
  useEffect(() => setLimit(PAGE), [kb, title]);
  const stats = useQuery({ queryKey: ["kb", "stats", kb], queryFn: () => kbStats(kb) });
  const tree = useQuery({ queryKey: ["kb", "kbs"], queryFn: () => kbTree(ROOT) });
  const docs = useQuery({ queryKey: ["kb", "docs", kb, title, limit], queryFn: () => kbDocumentsPage(kb, limit, title), placeholderData: (old) => old });
  const hits = useQuery({ queryKey: ["kb", "search", kb, q], queryFn: () => kbSearch(q, kb), enabled: q !== "" });
  const topics = (tree.data?.nodes ?? [])
    .filter((n) => n.path.startsWith(`${ROOT}.`) && n.depth === 1 && (n.subtree ?? 0) > 0)
    .sort((a, b) => (b.subtree ?? 0) - (a.subtree ?? 0));
  const allDocs = (tree.data?.nodes ?? []).find((n) => n.path === ROOT)?.subtree ?? null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next = draft.trim();
    setParams(next ? { q: next } : {});
  };
  const list = docs.data?.documents ?? [];
  const total = docs.data?.total ?? list.length;

  return (
    <>
      <section className="card kb-live">
        {stats.isError ? (
          <p className="error" role="alert">
            Банк статей сейчас недоступен: {stats.error.message}
          </p>
        ) : (
          <div className="kb-numbers" aria-live="polite">
            <div>
              <strong>{stats.data ? fmt(stats.data.documents) : "…"}</strong>
              <span className="muted">{stats.data ? plural(stats.data.documents ?? 0, "статья", "статьи", "статей").replace(/^\S+\s/, "") : "статей"}</span>
            </div>
            <div>
              <strong>{stats.data ? fmt(stats.data.chunks) : "…"}</strong>
              <span className="muted">отрывков для поиска</span>
            </div>
            {stats.data?.facts !== undefined && (
              <div>
                <strong>{fmt(stats.data.facts)}</strong>
                <span className="muted">утверждений с цитатами</span>
              </div>
            )}
            {stats.data?.year_from && (
              <div>
                <strong>
                  {stats.data.year_from}–{stats.data.year_to}
                </strong>
                <span className="muted">годы публикаций</span>
              </div>
            )}
          </div>
        )}

        <form className="search-row" onSubmit={submit} role="search">
          <label htmlFor="kb-q" className="sr-only">
            Поиск по статьям
          </label>
          <input
            id="kb-q"
            type="search"
            className="search"
            placeholder="Спросите своими словами: влияют ли ESG-рейтинги на прибыль?"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" className="btn-primary">
            Найти
          </button>
        </form>

        {topics.length > 0 && (
          <div className="kb-topics">
            <span className="muted">Темы:</span>
            <div className="chips-row" role="group" aria-label="Тема банка статей">
              <button type="button" className={kb === ROOT ? "chip active" : "chip"} aria-pressed={kb === ROOT} onClick={() => setKb(ROOT)}>
                Все темы{allDocs ? ` · ${fmt(allDocs)}` : ""}
              </button>
              {topics.map((t) => (
                <button key={t.path} type="button" className={kb === t.path ? "chip active" : "chip"} aria-pressed={kb === t.path} onClick={() => setKb(t.path)}>
                  {t.title} · {fmt(t.subtree ?? 0)}
                </button>
              ))}
            </div>
          </div>
        )}

        {q !== "" && (
          <div className="hits">
            <h2 className="h3">Найдено по запросу «{q}»</h2>
            {hits.isPending && <p className="muted">Ищу…</p>}
            {hits.isError && (
              <p className="error" role="alert">
                {hits.error.message}
              </p>
            )}
            {hits.data?.length === 0 && <p className="muted">Ничего не найдено. Попробуйте сказать иначе или выбрать «Все темы».</p>}
            {hits.data?.map((h) => (
              <article key={h.chunk_id} className="hit">
                <div className="kb-meta">
                  <span className="mono">{h.year ?? "—"}</span> ·{" "}
                  <Link to={`/knowledge/article/${encodeURIComponent(h.doc_id)}`}>{h.title}</Link>
                  {h.pages.length > 0 && <span> · с. {h.pages.join(", ")}</span>}
                </div>
                {h.headings.length > 0 && <div className="muted">{h.headings.join(" › ")}</div>}
                <p className="hit-text">{h.text.length > 600 ? `${h.text.slice(0, 600)}…` : h.text}</p>
                <div>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => navigate("/hypotheses", { state: { ref: refFromHit(h, kb) } })}
                  >
                    Предложить идею по этой статье
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="card kb-articles" aria-labelledby="kb-articles-title">
        <div className="viz-head">
          <h2 className="h2" id="kb-articles-title">
            Все статьи{docs.isSuccess ? ` · ${fmt(total)}` : ""}
          </h2>
          <form
            className="search-row kb-title-search"
            onSubmit={(e) => {
              e.preventDefault();
              setTitle(titleDraft.trim());
            }}
          >
            <label htmlFor="kb-title" className="sr-only">
              Найти статью по названию
            </label>
            <input id="kb-title" type="search" className="search" placeholder="Найти по названию…" value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} />
            <button type="submit" className="btn-ghost">
              Найти
            </button>
          </form>
        </div>
        {docs.isPending && <p className="muted">Загрузка…</p>}
        {docs.isError && (
          <p className="error" role="alert">
            Не удалось загрузить список статей: {docs.error.message}
          </p>
        )}
        {docs.isSuccess && total === 0 && <p className="muted">Статей не найдено.</p>}
        {list.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col" className="kb-year">Год</th>
                  <th scope="col">Статья</th>
                </tr>
              </thead>
              <tbody>
                {list.map((d) => (
                  <tr key={d.doc_id}>
                    <td className="mono">{d.year ?? "—"}</td>
                    <td>
                      <Link to={`/knowledge/article/${encodeURIComponent(d.doc_id)}`}>{d.title || d.doc_id}</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.length < total && (
          <div className="kb-more">
            <span className="muted">
              Показано {fmt(list.length)} из {fmt(total)}
            </span>
            <button type="button" className="btn-ghost" disabled={docs.isFetching} onClick={() => setLimit(limit + PAGE)}>
              {docs.isFetching ? "Загружаю…" : `Показать ещё ${Math.min(PAGE, total - list.length)}`}
            </button>
          </div>
        )}
      </section>
    </>
  );
}
