import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { type ApiTokenRow, createToken, listTokens, revokeToken } from "../api/auth";
import { useMe } from "../auth/useAuth";

const DAYS = [30, 90, 180, 365];
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("ru-RU") : "—");

function status(t: ApiTokenRow): string {
  if (t.revoked_at) return "отозван";
  return t.active ? "действует" : "истёк";
}

/** Токен показывается один раз — его нужно сохранить сразу. */
function Shown({ token, name, onClose }: { token: string; name: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(token).then(() => setCopied(true));
  };
  return (
    <div className="card accent" role="status">
      <p>{`Токен «${name}» создан. Скопируйте его сейчас — больше он не покажется:`}</p>
      <p className="mono token-value">{token}</p>
      <div className="actions">
        <button type="button" className="btn-primary" onClick={copy}>
          {copied ? "Скопировано" : "Скопировать"}
        </button>
        <button type="button" className="btn-ghost" onClick={onClose}>
          Сохранил, закрыть
        </button>
      </div>
      <p className="muted">Храните токен как пароль: в переменной окружения или менеджере паролей, не в коде и не в ноутбуке, который вы кому-то отправите.</p>
    </div>
  );
}

function Examples() {
  const site = window.location.origin;
  return (
    <section className="card">
      <h2 className="h2">Как подключиться</h2>
      <ol className="steps">
        <li>Создайте токен ниже и сохраните его.</li>
        <li>
          Передавайте его в заголовке <code>Authorization: Bearer …</code> — адреса с версией <code>/api/v1/…</code>.
        </li>
        <li>
          Все методы, параметры и ответы — в{" "}
          <a href="/api/docs" target="_blank" rel="noopener noreferrer">
            описании API
          </a>
          : там же можно вставить токен (кнопка «Authorize») и попробовать запросы.
        </li>
      </ol>
      <p className="muted">Командная строка:</p>
      <pre className="code">
        <code>{`curl -H "Authorization: Bearer $ESG_TOKEN" ${site}/api/v1/datasets`}</code>
      </pre>
      <p className="muted">Python:</p>
      <pre className="code">
        <code>{`import os, requests
api = requests.Session()
api.headers["Authorization"] = "Bearer " + os.environ["ESG_TOKEN"]
datasets = api.get("${site}/api/v1/datasets").json()`}</code>
      </pre>
      <p className="muted">Пакет esg (cli/README.md):</p>
      <pre className="code">
        <code>{`esg login --token --url ${site}
esg datasets`}</code>
      </pre>
    </section>
  );
}

export function ApiAccess() {
  const qc = useQueryClient();
  const me = useMe();
  const owner = me.data?.role === "owner";
  const [all, setAll] = useState(false);
  const tokens = useQuery({ queryKey: ["tokens", all], queryFn: () => listTokens(all) });
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write">("read");
  const [days, setDays] = useState(90);
  const [shown, setShown] = useState<{ token: string; name: string } | null>(null);
  const [confirm, setConfirm] = useState<number | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["tokens"] });
  const create = useMutation({
    mutationFn: () => createToken({ name: name.trim(), scope, days }),
    onSuccess: (t) => {
      setShown({ token: t.token, name: t.name });
      setName("");
      refresh();
    },
  });
  const revoke = useMutation({
    mutationFn: revokeToken,
    onSuccess: () => {
      setConfirm(null);
      refresh();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  const list = Array.isArray(tokens.data) ? tokens.data : [];
  const error = create.error ?? revoke.error ?? tokens.error;

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">ОТКРЫТЫЙ API</span>
        <h1 className="page-title">Доступ к API</h1>
        <p className="lead">
          Подключайте к платформе свои программы и скрипты: наборы данных, расчёты, проверки — то же, что на сайте. Вход —
          по личному токену, права — как у вашей роли.
        </p>
      </section>
      {shown && <Shown token={shown.token} name={shown.name} onClose={() => setShown(null)} />}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
      <form className="card user-form" onSubmit={submit}>
        <h2 className="h2">Новый токен</h2>
        <label className="field inline grow">
          Название
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="например, скрипт выгрузки" required maxLength={128} />
        </label>
        <label className="field inline">
          Права
          <select value={scope} onChange={(e) => setScope(e.target.value as "read" | "write")}>
            <option value="read">только чтение</option>
            <option value="write">чтение и запуск расчётов</option>
          </select>
        </label>
        <label className="field inline">
          Срок
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {DAYS.map((d) => (
              <option key={d} value={d}>
                {`${d} дней`}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          Создать токен
        </button>
      </form>
      <section className="card table-wrap">
        <h2 className="h2">{all ? "Токены всех пользователей" : "Мои токены"}</h2>
        {owner && (
          <label className="check">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Показать токены всех
            пользователей
          </label>
        )}
        {list.length === 0 ? (
          <p className="empty">Токенов пока нет.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                {all && <th scope="col">Логин</th>}
                <th scope="col">Название</th>
                <th scope="col">Начало токена</th>
                <th scope="col">Права</th>
                <th scope="col">Создан</th>
                <th scope="col">Действует до</th>
                <th scope="col">Последний запрос</th>
                <th scope="col">Состояние</th>
                <th scope="col">Действия</th>
              </tr>
            </thead>
            <tbody>
              {list.map((t) => (
                <tr key={t.id}>
                  {all && <td className="mono">{t.login}</td>}
                  <td>{t.name}</td>
                  <td className="mono">{t.prefix}…</td>
                  <td>{t.scope === "write" ? "чтение и запуск" : "только чтение"}</td>
                  <td>{day(t.created_at)}</td>
                  <td>{day(t.expires_at)}</td>
                  <td>{day(t.last_used_at)}</td>
                  <td>{status(t)}</td>
                  <td>
                    <div className="actions">
                    {t.active &&
                      (confirm === t.id ? (
                        <>
                          <button type="button" className="btn-ghost" onClick={() => revoke.mutate(t.id)} disabled={revoke.isPending}>
                            Да, отозвать
                          </button>
                          <button type="button" className="btn-ghost" onClick={() => setConfirm(null)}>
                            Отмена
                          </button>
                        </>
                      ) : (
                        <button type="button" className="btn-ghost" onClick={() => setConfirm(t.id)}>
                          Отозвать
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <Examples />
    </>
  );
}
