import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useMe } from "../auth/useAuth";

interface Snapshot {
  id: number;
  version: string;
  sha256: string;
  row_count: number | null;
  storage_path: string;
  created_at: string;
  runs: number;
}

export interface DatasetDetail {
  code: string;
  title: string;
  description: string;
  source_url: string;
  license: string;
  access_level: "public" | "nda";
  created_at: string;
  can_see_files: boolean;
  snapshots: Snapshot[];
  experiments: string[];
}

interface ServerFile {
  path: string;
  bytes: number;
  modified: string;
  snapshot: string;
}

type DatasetFields = Pick<DatasetDetail, "title" | "description" | "source_url" | "license" | "access_level">;

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const json = typeof init?.body === "string";
  const res = await fetch(`/api/datasets${path}`, {
    credentials: "same-origin",
    ...(json ? { headers: { "Content-Type": "application/json" } } : {}),
    ...init,
  });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) {
    if (res.status === 413) throw new Error("Файл слишком большой — положите его в каталог датасета на сервере");
    const d = body?.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? "Проверьте поля формы" : `Ошибка ${res.status}`);
  }
  return body;
}

const getDataset = (code: string) => call<DatasetDetail>(`/${code}`);
const listFiles = (code: string) => call<ServerFile[]>(`/${code}/files`);
export const createDataset = (f: DatasetFields) => call<DatasetDetail>("", { method: "POST", body: JSON.stringify(f) });
const patchDataset = (code: string, f: Partial<DatasetFields>) =>
  call<DatasetDetail>(`/${code}`, { method: "PATCH", body: JSON.stringify(f) });
const registerFile = (code: string, path: string, version: string) =>
  call<DatasetDetail>(`/${code}/snapshots/register`, { method: "POST", body: JSON.stringify({ path, version }) });
function uploadSnapshot(code: string, file: File, version: string): Promise<DatasetDetail> {
  const form = new FormData();
  form.append("file", file);
  form.append("version", version);
  return call<DatasetDetail>(`/${code}/snapshots`, { method: "POST", body: form });
}

const size = (b: number) => (b < 2 ** 20 ? `${Math.max(1, Math.round(b / 1024))} КБ` : `${(b / 2 ** 20).toFixed(1).replace(".", ",")} МБ`);
const day = (s: string) => new Date(s).toLocaleDateString("ru-RU");

/** Поля карточки датасета — для создания и правки. */
export function DatasetForm({
  initial,
  canSetNda,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  initial: DatasetFields;
  canSetNda: boolean;
  submitLabel: string;
  pending: boolean;
  error: string;
  onSubmit: (f: DatasetFields) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState(initial);
  const set = (k: keyof DatasetFields) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form
      className="card dataset-form"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit(f);
      }}
    >
      <label className="field">
        Название
        <input value={f.title} onChange={set("title")} required minLength={3} maxLength={512} />
      </label>
      <label className="field">
        Описание — что внутри, охват, особенности шкал
        <textarea value={f.description} onChange={set("description")} rows={4} />
      </label>
      <div className="form-grid">
        <label className="field">
          Источник (ссылка)
          <input value={f.source_url} onChange={set("source_url")} maxLength={1024} placeholder="https://…" />
        </label>
        <label className="field">
          Лицензия и условия
          <input value={f.license} onChange={set("license")} maxLength={256} />
        </label>
        <label className="field span-2">
          Доступ
          <select value={f.access_level} onChange={set("access_level")} disabled={!canSetNda}>
            <option value="public">открытый</option>
            <option value="nda">NDA — файлы только для допущенных</option>
          </select>
        </label>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="review-form">
        <button type="submit" className="btn-primary" disabled={pending}>
          {submitLabel}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </form>
  );
}

export function NewDataset({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const me = useMe();
  const m = useMutation({
    mutationFn: createDataset,
    onSuccess: (ds) => {
      void qc.invalidateQueries({ queryKey: ["datasets"] });
      navigate(`/datasets/${ds.code}`);
    },
  });
  return (
    <DatasetForm
      initial={{ title: "", description: "", source_url: "", license: "", access_level: "public" }}
      canSetNda={me.data?.role === "owner"}
      submitLabel={m.isPending ? "Создаю…" : "Создать датасет"}
      pending={m.isPending}
      error={m.isError ? m.error.message : ""}
      onSubmit={(f) => m.mutate(f)}
      onCancel={onDone}
    />
  );
}

function AddSnapshot({ ds }: { ds: DatasetDetail }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [version, setVersion] = useState("");
  const files = useQuery({ queryKey: ["dataset-files", ds.code], queryFn: () => listFiles(ds.code) });
  const done = (d: DatasetDetail) => {
    qc.setQueryData(["dataset", ds.code], d);
    void qc.invalidateQueries({ queryKey: ["dataset-files", ds.code] });
    void qc.invalidateQueries({ queryKey: ["run-templates"] });
    setFile(null);
    setVersion("");
    if (input.current) input.current.value = "";
  };
  const upload = useMutation({ mutationFn: () => uploadSnapshot(ds.code, file as File, version), onSuccess: done });
  const register = useMutation({ mutationFn: (path: string) => registerFile(ds.code, path, version), onSuccess: done });
  const free = (files.data ?? []).filter((f) => !f.snapshot);
  const error = upload.error ?? register.error;
  return (
    <section className="card dataset-form">
      <h2 className="h2">Новый срез</h2>
      <p className="muted">
        Срез — неизменяемый файл: сервер считает его sha256, и запуск сверяет хеш перед расчётом. Поменялись данные —
        это новый срез, а не правка старого.
      </p>
      <label className="field">
        Версия (по умолчанию — сегодняшняя дата)
        <input value={version} onChange={(e) => setVersion(e.target.value)} maxLength={64} placeholder="2026-10-30" />
      </label>
      <div className="form-grid">
        <label className="field span-2">
          Загрузить файл (до 60 МБ)
          <input ref={input} type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
      </div>
      <div>
        <button type="button" className="btn-primary" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>
          {upload.isPending ? "Загружаю…" : "Загрузить срез"}
        </button>
      </div>
      <h3 className="h3">…или зарегистрировать файл с сервера</h3>
      <p className="muted">
        Большие файлы кладут в каталог <span className="mono">{ds.code}</span> папки данных сервера и регистрируют здесь.
      </p>
      {files.isError && <p className="error">{files.error.message}</p>}
      {files.isSuccess && free.length === 0 && <p className="muted">Незарегистрированных файлов в каталоге нет.</p>}
      {free.length > 0 && (
        <ul className="list">
          {free.map((f) => (
            <li key={f.path} className="file-row">
              <span className="mono">{f.path}</span>
              <span className="muted">
                {size(f.bytes)} · {day(f.modified)}
              </span>
              <button type="button" className="link-btn" disabled={register.isPending} onClick={() => register.mutate(f.path)}>
                сделать срезом
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
    </section>
  );
}

export function DatasetPage() {
  const { code = "" } = useParams();
  const qc = useQueryClient();
  const me = useMe();
  const role = me.data?.role;
  const canEdit = role === "researcher" || role === "owner";
  const [editing, setEditing] = useState(false);
  const q = useQuery({ queryKey: ["dataset", code], queryFn: () => getDataset(code) });
  const edit = useMutation({
    mutationFn: (f: DatasetFields) => patchDataset(code, f),
    onSuccess: (d) => {
      qc.setQueryData(["dataset", code], d);
      void qc.invalidateQueries({ queryKey: ["datasets"] });
      setEditing(false);
    },
  });
  if (q.isError) {
    return (
      <p className="error" role="alert">
        {q.error.message}
      </p>
    );
  }
  const ds = q.data;
  if (!ds) return <p className="muted">Загрузка…</p>;
  return (
    <>
      <section className="page-head">
        <span className="eyebrow">
          <Link to="/knowledge">БАЗА ЗНАНИЙ</Link> · ДАТАСЕТ
        </span>
        <h1 className="page-title">
          <span className="mono">{ds.code}</span> · {ds.title}
        </h1>
        <div className="run-head">
          {ds.access_level === "nda" ? <span className="badge st-review">NDA</span> : <span className="badge st-done">открытый</span>}
          <span className="muted">заведён {day(ds.created_at)}</span>
          {canEdit && !editing && (
            <button type="button" className="btn-ghost" onClick={() => setEditing(true)}>
              Редактировать
            </button>
          )}
        </div>
      </section>
      {editing ? (
        <DatasetForm
          initial={{
            title: ds.title,
            description: ds.description,
            source_url: ds.source_url,
            license: ds.license,
            access_level: ds.access_level,
          }}
          canSetNda={role === "owner"}
          submitLabel={edit.isPending ? "Сохраняю…" : "Сохранить"}
          pending={edit.isPending}
          error={edit.isError ? edit.error.message : ""}
          onSubmit={(f) => edit.mutate(f)}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <section className="card">
          <p>{ds.description || <span className="muted">Описания нет.</span>}</p>
          <dl className="run-facts">
            <div className="run-fact">
              <dt>Источник</dt>
              <dd>
                {ds.source_url.startsWith("http") ? (
                  <a href={ds.source_url} target="_blank" rel="noreferrer">
                    {ds.source_url}
                  </a>
                ) : (
                  <span className="muted">{ds.source_url || "не указан"}</span>
                )}
              </dd>
            </div>
            <div className="run-fact">
              <dt>Лицензия</dt>
              <dd>{ds.license || <span className="muted">не указана</span>}</dd>
            </div>
            <div className="run-fact">
              <dt>Эксперименты</dt>
              <dd>
                {ds.experiments.length === 0 ? (
                  <span className="muted">пока нет</span>
                ) : (
                  ds.experiments.map((e, i) => (
                    <span key={e}>
                      {i > 0 && ", "}
                      <Link to={`/experiments/${e}`} className="mono">
                        {e}
                      </Link>
                    </span>
                  ))
                )}
              </dd>
            </div>
          </dl>
        </section>
      )}
      <section className="card">
        <h2 className="h2">Срезы</h2>
        {ds.snapshots.length === 0 ? (
          <p className="muted">Срезов нет — запустить эксперимент на этом датасете пока нельзя.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Версия</th>
                  <th scope="col">sha256</th>
                  <th scope="col" className="num">
                    Строк
                  </th>
                  <th scope="col" className="num">
                    Запусков
                  </th>
                  <th scope="col">Файл</th>
                </tr>
              </thead>
              <tbody>
                {ds.snapshots.map((s) => (
                  <tr key={s.id}>
                    <td className="mono">{s.version}</td>
                    <td className="mono" title={s.sha256}>
                      {s.sha256.slice(0, 16)}…
                    </td>
                    <td className="num mono">{s.row_count?.toLocaleString("ru-RU") ?? "—"}</td>
                    <td className="num mono">{s.runs}</td>
                    <td className="mono run-path">{ds.can_see_files ? s.storage_path || "—" : "под NDA"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {canEdit && ds.can_see_files && <AddSnapshot ds={ds} />}
    </>
  );
}
