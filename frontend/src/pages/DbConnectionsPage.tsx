import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import {
  createConnection,
  DB_KINDS,
  type DbConnection,
  type DbConnectionIn,
  deleteConnection,
  listConnections,
  updateConnection,
} from "../api/studio";

const EMPTY: DbConnectionIn = { title: "", kind: "postgresql", host: "", port: 5432, database: "", username: "", password: "", allow_write: false };

/** Подключения к внешним базам для Студии (владелец платформы). Пароль хранится зашифрованным и не показывается. */
export function DbConnections() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["studio", "connections"], queryFn: listConnections });
  const [form, setForm] = useState<DbConnectionIn>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["studio", "connections"] });
  const save = useMutation({
    mutationFn: () => (editing ? updateConnection(editing, form) : createConnection(form)),
    onSuccess: () => {
      setForm(EMPTY);
      setEditing(null);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: deleteConnection,
    onSuccess: () => {
      setConfirm(null);
      refresh();
    },
  });
  const edit = (c: DbConnection) => {
    setEditing(c.code);
    setForm({ title: c.title, kind: c.kind, host: c.host, port: c.port, database: c.database, username: c.username, password: null, allow_write: c.allow_write });
  };
  const set = (patch: Partial<DbConnectionIn>) => setForm((f) => ({ ...f, ...patch }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const rows = Array.isArray(list.data) ? list.data : [];
  const error = save.error ?? remove.error ?? list.error;

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">СЛУЖЕБНОЕ</span>
        <h1 className="page-title">Подключения к базам</h1>
        <p className="lead">
          Внешние базы данных для Студии: узлы «Импорт: База данных» и «Экспорт: База данных» выбирают подключение по коду. Пароль хранится
          на сервере зашифрованным и никому не показывается — его получает только исполнитель на время расчёта. Для импорта лучше завести в базе
          пользователя только для чтения.
        </p>
      </section>
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
      <form className="card user-form" onSubmit={submit}>
        <h2 className="h2">{editing ? `Изменить ${editing}` : "Новое подключение"}</h2>
        <label className="field inline grow">
          Название
          <input value={form.title} onChange={(e) => set({ title: e.target.value })} required maxLength={256} />
        </label>
        <label className="field inline">
          Тип базы
          <select
            value={form.kind}
            onChange={(e) => {
              const k = DB_KINDS.find((x) => x.value === e.target.value);
              set({ kind: e.target.value as DbConnection["kind"], port: k?.port ?? form.port });
            }}
          >
            {DB_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field inline grow">
          Сервер
          <input value={form.host} onChange={(e) => set({ host: e.target.value })} required placeholder="адрес в сети лаборатории" />
        </label>
        <label className="field inline">
          Порт
          <input type="number" value={form.port ?? ""} onChange={(e) => set({ port: e.target.value ? Number(e.target.value) : null })} min={1} max={65535} />
        </label>
        <label className="field inline">
          База
          <input value={form.database} onChange={(e) => set({ database: e.target.value })} />
        </label>
        <label className="field inline">
          Пользователь
          <input value={form.username} onChange={(e) => set({ username: e.target.value })} autoComplete="off" />
        </label>
        <label className="field inline">
          Пароль
          <input
            type="password"
            value={form.password ?? ""}
            onChange={(e) => set({ password: e.target.value })}
            autoComplete="new-password"
            placeholder={editing ? "не менять — оставьте пустым" : ""}
          />
        </label>
        <label className="check">
          <input type="checkbox" checked={form.allow_write} onChange={(e) => set({ allow_write: e.target.checked })} /> Разрешить запись (узел
          «Экспорт: База данных»)
        </label>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {editing ? "Сохранить" : "Добавить"}
        </button>
        {editing && (
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              setEditing(null);
              setForm(EMPTY);
            }}
          >
            Отмена
          </button>
        )}
      </form>
      <section className="card table-wrap">
        <h2 className="h2">Подключения</h2>
        {rows.length === 0 ? (
          <p className="empty">Подключений пока нет.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Код</th>
                <th scope="col">Название</th>
                <th scope="col">Тип</th>
                <th scope="col">Сервер</th>
                <th scope="col">База</th>
                <th scope="col">Пользователь</th>
                <th scope="col">Запись</th>
                <th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.code}>
                  <td className="mono">{c.code}</td>
                  <td>{c.title}</td>
                  <td>{DB_KINDS.find((k) => k.value === c.kind)?.label ?? c.kind}</td>
                  <td className="mono">
                    {c.host}
                    {c.port ? `:${c.port}` : ""}
                  </td>
                  <td className="mono">{c.database}</td>
                  <td className="mono">
                    {c.username}
                    {c.has_password ? "" : " (без пароля)"}
                  </td>
                  <td>{c.allow_write ? "разрешена" : "нет"}</td>
                  <td>
                    <div className="actions">
                      <button type="button" className="btn-ghost" onClick={() => edit(c)}>
                        Изменить
                      </button>
                      {confirm === c.code ? (
                        <button type="button" className="btn-ghost" onClick={() => remove.mutate(c.code)} disabled={remove.isPending}>
                          Да, удалить
                        </button>
                      ) : (
                        <button type="button" className="btn-ghost" onClick={() => setConfirm(c.code)}>
                          Удалить
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
