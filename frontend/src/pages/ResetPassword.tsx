import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { resetByLink } from "../api/auth";
import { ME_KEY } from "../auth/useAuth";
import { LoginCard } from "./Login";

/** Новый пароль по ссылке из письма «Забыли пароль?». Токен — после «#» в адресе ссылки. */
export function ResetPassword() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [token] = useState(() => window.location.hash.replace(/^#/, ""));
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const m = useMutation({
    mutationFn: () => resetByLink(token, next),
    onSuccess: (u) => {
      qc.setQueryData(ME_KEY, u);
      navigate("/", { replace: true });
    },
  });
  const mismatch = again !== "" && again !== next;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) m.mutate();
  };
  return (
    <LoginCard onSubmit={submit}>
      <h2 className="h2" style={{ margin: 0 }}>Новый пароль</h2>
      {!token ? (
        <p className="error" role="alert">
          В ссылке нет ключа сброса. Откройте ссылку из письма целиком или запросите сброс ещё раз.
        </p>
      ) : (
        <>
          <p className="muted" style={{ margin: 0 }}>Не короче 10 символов, с буквами и цифрами.</p>
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
          <button type="submit" className="btn-primary" disabled={m.isPending || mismatch}>
            Сохранить и войти
          </button>
        </>
      )}
      <button type="button" className="link-btn" onClick={() => navigate("/", { replace: true })}>
        Ко входу
      </button>
    </LoginCard>
  );
}
