import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import {
  changePassword,
  createUser,
  listUsers,
  type NewUser,
  patchUser,
  resetPassword,
  type Role,
} from "../api/auth";
import { ME_KEY } from "../auth/useAuth";
import { AuditLog } from "./AuditLog";

const ROLES: Array<{ value: Role; label: string }> = [
  { value: "reader", label: "reader — чтение" },
  { value: "researcher", label: "researcher — эксперименты, CR" },
  { value: "reviewer", label: "reviewer — рецензии" },
  { value: "owner", label: "owner — всё и доступы" },
];

/** Временный пароль показывается один раз — его нужно передать человеку. */
function TempPassword({ user, onClose }: { user: NewUser; onClose: () => void }) {
  return (
    <div className="card accent" role="status">
      <p>
        Временный пароль для <strong>{user.login}</strong>: <span className="mono">{user.temporary_password}</span>
      </p>
      <p className="muted">Показывается один раз. При первом входе пользователь задаст свой пароль.</p>
      <button type="button" className="btn-ghost" onClick={onClose}>
        Понятно
      </button>
    </div>
  );
}

export function Users() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const [shown, setShown] = useState<NewUser | null>(null);
  const [login, setLogin] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("reader");
  const [nda, setNda] = useState(false);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["users"] });
  const create = useMutation({
    mutationFn: () => createUser({ login: login.trim(), full_name: fullName.trim(), role, nda_access: nda }),
    onSuccess: (u) => {
      setShown(u);
      setLogin("");
      setFullName("");
      refresh();
    },
  });
  const reset = useMutation({ mutationFn: resetPassword, onSuccess: (u) => setShown(u) });
  const patch = useMutation({
    mutationFn: (v: { login: string; patch: Parameters<typeof patchUser>[1] }) => patchUser(v.login, v.patch),
    onSuccess: refresh,
  });
  const error = create.error ?? reset.error ?? patch.error;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  const list = Array.isArray(users.data) ? users.data : [];

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">ДОСТУПЫ</span>
        <h1 className="page-title">Пользователи</h1>
        <p className="lead">
          Учётные записи платформы, роли и допуск к данным под NDA. Новому пользователю выдаётся временный пароль.
        </p>
      </section>
      {shown && <TempPassword user={shown} onClose={() => setShown(null)} />}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
      <form className="card user-form" onSubmit={submit}>
        <h2 className="h2">Новый пользователь</h2>
        <label className="field inline">
          Логин
          <input value={login} onChange={(e) => setLogin(e.target.value)} required pattern="[A-Za-z0-9._@\-]+" />
        </label>
        <label className="field inline grow">
          ФИО
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </label>
        <label className="field inline">
          Роль
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={nda} onChange={(e) => setNda(e.target.checked)} /> NDA-допуск
        </label>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          Создать
        </button>
      </form>
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Логин</th>
              <th scope="col">ФИО</th>
              <th scope="col">Роль</th>
              <th scope="col">NDA</th>
              <th scope="col">Статус</th>
              <th scope="col">Действия</th>
            </tr>
          </thead>
          <tbody>
            {list.map((u) => (
              <tr key={u.login}>
                <td className="mono">{u.login}</td>
                <td>{u.full_name}</td>
                <td>
                  <label className="sr-only" htmlFor={`role-${u.login}`}>
                    Роль {u.login}
                  </label>
                  <select
                    id={`role-${u.login}`}
                    value={u.role}
                    onChange={(e) => patch.mutate({ login: u.login, patch: { role: e.target.value as Role } })}
                  >
                    {ROLES.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.value}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`NDA-допуск ${u.login}`}
                    checked={u.nda_access}
                    onChange={(e) => patch.mutate({ login: u.login, patch: { nda_access: e.target.checked } })}
                  />
                </td>
                <td>
                  {u.is_active === false ? "заблокирован" : u.must_change_password ? "ждёт смены пароля" : "активен"}
                </td>
                <td className="actions">
                  <button type="button" className="btn-ghost" onClick={() => reset.mutate(u.login)}>
                    Сбросить пароль
                  </button>
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => patch.mutate({ login: u.login, patch: { is_active: u.is_active === false } })}
                  >
                    {u.is_active === false ? "Разблокировать" : "Заблокировать"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <AuditLog />
    </>
  );
}

/** Смена своего пароля; при временном пароле — единственная доступная страница. */
export function ChangePassword({ forced = false }: { forced?: boolean }) {
  const qc = useQueryClient();
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const m = useMutation({
    mutationFn: () => changePassword(old, next),
    onSuccess: (u) => {
      qc.setQueryData(ME_KEY, u);
      setOld("");
      setNext("");
      setAgain("");
    },
  });
  const mismatch = again !== "" && again !== next;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) m.mutate();
  };
  return (
    <div className={forced ? "login-wrap" : ""}>
      <form className="card login-card" onSubmit={submit}>
        <h1 className="page-title" style={{ fontSize: 24 }}>
          {forced ? "Задайте свой пароль" : "Смена пароля"}
        </h1>
        {forced && <p className="muted">Вы вошли по временному паролю. Придумайте свой — не короче 10 символов, с буквами и цифрами.</p>}
        <label className="field">
          {forced ? "Временный пароль" : "Текущий пароль"}
          <input type="password" autoComplete="current-password" value={old} onChange={(e) => setOld(e.target.value)} required />
        </label>
        <label className="field">
          Новый пароль
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={10} />
        </label>
        <label className="field">
          Новый пароль ещё раз
          <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
        </label>
        {mismatch && <p className="error">Пароли не совпадают</p>}
        {m.isError && (
          <p className="error" role="alert">
            {m.error.message}
          </p>
        )}
        {m.isSuccess && !forced && <p role="status">Пароль изменён.</p>}
        <button type="submit" className="btn-primary" disabled={m.isPending || mismatch}>
          Сохранить
        </button>
      </form>
    </div>
  );
}
