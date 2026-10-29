import { type FormEvent, useState } from "react";

import { useLogin } from "../auth/useAuth";

export function Login() {
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useLogin();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate({ login: loginName.trim(), password });
  };

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <div>
          <span className="eyebrow">НИЦ ИИ · УНИВЕРСИТЕТ «ДУБНА»</span>
          <h1 style={{ margin: "6px 0 0", fontSize: 28 }}>ESG Open Research</h1>
        </div>
        <label className="field">
          Логин
          <input
            autoComplete="username"
            value={loginName}
            onChange={(e) => setLoginName(e.target.value)}
            required
          />
        </label>
        <label className="field">
          Пароль
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {mutation.isError && (
          <p className="error" role="alert">
            {mutation.error.message}
          </p>
        )}
        <button type="submit" className="btn-primary" disabled={mutation.isPending}>
          Войти
        </button>
      </form>
    </div>
  );
}
