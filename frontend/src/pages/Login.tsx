import { useMutation } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";

import { forgotPassword } from "../api/auth";
import { useLogin } from "../auth/useAuth";
import { LangSwitch } from "../components/LangSwitch";
import { SiteFooter } from "../components/SiteFooter";
import { ORG, WITH_LAB } from "../org";

function Head() {
  return (
    <>
      <div className="login-lang">
        <LangSwitch />
      </div>
      <div>
        <span className="eyebrow">{ORG.toUpperCase()}</span>
        <h1 style={{ margin: "6px 0 0", fontSize: 28 }}>ESG Open Research</h1>
        <p className="muted" style={{ margin: "6px 0 0" }}>{WITH_LAB.charAt(0).toUpperCase() + WITH_LAB.slice(1)}</p>
      </div>
    </>
  );
}

export function LoginCard({ onSubmit, children }: { onSubmit: (e: FormEvent) => void; children: ReactNode }) {
  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={onSubmit}>
        <Head />
        {children}
      </form>
      <SiteFooter />
    </div>
  );
}

/** «Забыли пароль?»: ссылка для нового пароля приходит на почту из профиля. */
function Forgot({ initial, onBack }: { initial: string; onBack: () => void }) {
  const [who, setWho] = useState(initial);
  const m = useMutation({ mutationFn: () => forgotPassword(who.trim()) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <LoginCard onSubmit={submit}>
      <h2 className="h2" style={{ margin: 0 }}>Сброс пароля</h2>
      {m.isSuccess ? (
        <p role="status">{m.data.detail}</p>
      ) : (
        <>
          <p className="muted" style={{ margin: 0 }}>
            Пришлём на вашу почту ссылку, по которой можно задать новый пароль.
          </p>
          <label className="field">
            Логин или почта
            <input autoComplete="username" value={who} onChange={(e) => setWho(e.target.value)} required />
          </label>
          {m.isError && (
            <p className="error" role="alert">
              {m.error.message}
            </p>
          )}
          <button type="submit" className="btn-primary" disabled={m.isPending}>
            Прислать ссылку
          </button>
        </>
      )}
      <button type="button" className="link-btn" onClick={onBack}>
        Вернуться ко входу
      </button>
    </LoginCard>
  );
}

export function Login() {
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [forgot, setForgot] = useState(false);
  const mutation = useLogin();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate({ login: loginName.trim(), password });
  };

  if (forgot) return <Forgot initial={loginName.trim()} onBack={() => setForgot(false)} />;

  return (
    <LoginCard onSubmit={submit}>
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
      <button type="button" className="link-btn" onClick={() => setForgot(true)}>
        Забыли пароль?
      </button>
    </LoginCard>
  );
}
