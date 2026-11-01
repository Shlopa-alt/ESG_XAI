import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { kbTree } from "../api/kb";
import {
  IMPORT_BADGE,
  IMPORT_STATUS,
  importByDoi,
  type KbImport,
  listImports,
  retryImport,
  uploadPdf,
} from "../api/kbImports";
import { useMe } from "../auth/useAuth";

const ROOT = "esg";
const MB = 2 ** 20;
const when = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });

function BranchSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const tree = useQuery({ queryKey: ["kb", "kbs"], queryFn: () => kbTree(ROOT) });
  const nodes = (tree.data?.nodes ?? []).filter((n) => n.path === ROOT || n.path.startsWith(`${ROOT}.`));
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} required>
      {nodes.length === 0 && <option value={ROOT}>ESG</option>}
      {nodes.map((n) => (
        <option key={n.path} value={n.path}>
          {"  ".repeat(n.depth)}
          {n.title} ({n.path})
        </option>
      ))}
    </select>
  );
}

function ByFile() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [kb, setKb] = useState(ROOT);
  const [doi, setDoi] = useState("");
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [authors, setAuthors] = useState("");
  const m = useMutation({
    mutationFn: uploadPdf,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kb-imports"] });
      setFile(null);
      setDoi("");
      setTitle("");
      setYear("");
      setAuthors("");
      if (input.current) input.current.value = "";
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (file) m.mutate({ file, kb_path: kb, doi, title, year, authors });
  };
  return (
    <form className="card import-form" onSubmit={submit}>
      <h2 className="h2">PDF-файлом</h2>
      <p className="muted">
        Название, авторов, год и DOI разбор возьмёт из самого PDF. Поля ниже нужны, только если там их нет или они
        неверные. Статья без DOI попадёт в базу с пометкой «требует источника» и не сможет быть основанием CR.
      </p>
      <div className="form-grid">
        <label className="field span-2">
          Файл статьи (PDF, до 60 МБ)
          <input
            ref={input}
            type="file"
            accept="application/pdf,.pdf"
            required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label className="field span-2" htmlFor="imp-kb">
          Ветка базы знаний
          <BranchSelect id="imp-kb" value={kb} onChange={setKb} />
        </label>
        <label className="field">
          DOI
          <input value={doi} onChange={(e) => setDoi(e.target.value)} placeholder="10.3390/electronics14030417" />
        </label>
        <label className="field">
          Год
          <input value={year} onChange={(e) => setYear(e.target.value)} inputMode="numeric" pattern="(19|20)\d\d"
            placeholder="2025" />
        </label>
        <label className="field span-2">
          Название
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={1024} />
        </label>
        <label className="field span-2">
          Авторы — через точку с запятой
          <input value={authors} onChange={(e) => setAuthors(e.target.value)} placeholder="Hsu Y.-H.; Lin C.-Y." />
        </label>
      </div>
      {file && (
        <p className="muted">
          {file.name} · {(file.size / MB).toFixed(1).replace(".", ",")} МБ
        </p>
      )}
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      {m.isSuccess && (
        <p className="ok" role="status">
          Импорт №{m.data.id} в очереди — статус ниже.
        </p>
      )}
      <div>
        <button type="submit" className="btn-primary" disabled={m.isPending || !file}>
          {m.isPending ? "Загрузка…" : "Загрузить"}
        </button>
      </div>
    </form>
  );
}

function ByDoi() {
  const qc = useQueryClient();
  const [doi, setDoi] = useState("");
  const [kb, setKb] = useState(ROOT);
  const m = useMutation({
    mutationFn: () => importByDoi(doi, kb),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kb-imports"] });
      setDoi("");
    },
  });
  return (
    <form
      className="card import-form"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <h2 className="h2">По DOI</h2>
      <p className="muted">
        Для статей открытого доступа. Метаданные берутся из OpenAlex, PDF скачивается с сайта издателя или
        репозитория. Закрытую статью скачайте сами и загрузите файлом.
      </p>
      <label className="field">
        DOI или ссылка doi.org
        <input value={doi} onChange={(e) => setDoi(e.target.value)} required minLength={7}
          placeholder="https://doi.org/10.3390/electronics14030417" />
      </label>
      <label className="field" htmlFor="doi-kb">
        Ветка базы знаний
        <BranchSelect id="doi-kb" value={kb} onChange={setKb} />
      </label>
      {m.isError && (
        <p className="error" role="alert">
          {m.error.message}
        </p>
      )}
      {m.isSuccess && (
        <p className="ok" role="status">
          «{m.data.title || m.data.doi}» скачана, импорт №{m.data.id} в очереди.
        </p>
      )}
      <div>
        <button type="submit" className="btn-primary" disabled={m.isPending}>
          {m.isPending ? "Скачиваю…" : "Найти и загрузить"}
        </button>
      </div>
    </form>
  );
}

function Queue({ canRetry }: { canRetry: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["kb-imports"],
    queryFn: listImports,
    // пока что-то в очереди или разбирается — обновлять, чтобы статус сменился сам
    refetchInterval: (query) =>
      (query.state.data ?? []).some((i) => i.status === "queued" || i.status === "processing") ? 10_000 : false,
  });
  const retry = useMutation({
    mutationFn: retryImport,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kb-imports"] }),
  });
  const rows: KbImport[] = q.data ?? [];
  return (
    <section className="card">
      <h2 className="h2">Загруженные статьи</h2>
      {q.isError && (
        <p className="error" role="alert">
          {q.error.message}
        </p>
      )}
      {q.isSuccess && rows.length === 0 && <p className="muted">Через сайт статей ещё не загружали.</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">№</th>
                <th scope="col">Статья</th>
                <th scope="col">Ветка</th>
                <th scope="col">Статус</th>
                <th scope="col">Кто и когда</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id}>
                  <td className="mono">{i.id}</td>
                  <td>
                    {i.doc_id && (i.status === "done" || i.status === "duplicate") ? (
                      <Link to={`/knowledge/article/${encodeURIComponent(i.doc_id)}`}>{i.title || i.filename}</Link>
                    ) : (
                      <strong>{i.title || i.filename}</strong>
                    )}
                    <div className="muted">
                      {[i.year, i.doi && `DOI ${i.doi}`, i.source === "doi" ? "скачана по DOI" : i.filename]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {i.message && <div className="muted import-msg">{i.message}</div>}
                  </td>
                  <td className="mono">{i.kb_path}</td>
                  <td>
                    <span className={`badge ${IMPORT_BADGE[i.status]}`}>{IMPORT_STATUS[i.status]}</span>
                    {canRetry && i.status === "failed" && (
                      <div>
                        <button type="button" className="link-btn" onClick={() => retry.mutate(i.id)}>
                          повторить
                        </button>
                      </div>
                    )}
                  </td>
                  <td className="muted">
                    {i.author || "—"}
                    <div>{when(i.created_at)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function Import() {
  const me = useMe();
  const role = me.data?.role;
  const canImport = role === "researcher" || role === "owner";
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">БАЗА ЗНАНИЙ · ИМПОРТ</span>
        <h1 className="page-title">Импорт статей</h1>
        <p className="lead">
          Статья разбирается в KBRAG так же, как при импорте на сервере: текст, таблицы, формулы, рисунки. Затем она
          попадает в поиск выбранной ветки, а факты графа о ней появятся при следующем проходе модели.
        </p>
      </section>
      {canImport ? (
        <div className="grid-2">
          <ByFile />
          <ByDoi />
        </div>
      ) : (
        <p className="card muted">Загружать статьи могут исследователи; список загруженных виден всем.</p>
      )}
      <Queue canRetry={canImport} />
    </>
  );
}
