import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listAudit } from "../api/auth";

// Понятные названия для частых действий; остальное — как адрес
const ACTIONS: Array<[RegExp, string]> = [
  [/^POST \/api\/auth\/login$/, "вход"],
  [/^POST \/api\/auth\/logout$/, "выход"],
  [/^POST \/api\/auth\/change-password$/, "смена своего пароля"],
  [/^POST \/api\/users$/, "создан пользователь"],
  [/^POST \/api\/users\/[^/]+\/reset-password$/, "сброшен пароль пользователя"],
  [/^PATCH \/api\/users\//, "изменён пользователь"],
  [/^POST \/api\/hypotheses$/, "предложена идея"],
  [/^PATCH \/api\/hypotheses\//, "решение по идее"],
  [/^POST \/api\/hypotheses\/[^/]+\/experiment$/, "проверка из идеи"],
  [/^POST \/api\/experiments$/, "создана проверка"],
  [/^PATCH \/api\/experiments\//, "изменена проверка"],
  [/^POST \/api\/reviews$/, "рецензия на проверку"],
  [/^POST \/api\/change-requests$/, "создано предложение"],
  [/^PATCH \/api\/change-requests\//, "решение по предложению"],
  [/^POST \/api\/change-requests\/[^/]+\/reviews$/, "рецензия на предложение"],
];

function action(method: string, path: string): string {
  const key = `${method} ${path}`;
  return ACTIONS.find(([re]) => re.test(key))?.[1] ?? key;
}

export function AuditLog() {
  const [login, setLogin] = useState("");
  const q = useQuery({ queryKey: ["audit", login], queryFn: () => listAudit(login.trim() || undefined) });
  const rows = Array.isArray(q.data) ? q.data : [];
  return (
    <section className="card">
      <h2 className="h2">Журнал действий</h2>
      <label className="field inline">
        Пользователь
        <input value={login} onChange={(e) => setLogin(e.target.value)} placeholder="все" />
      </label>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Когда</th>
              <th scope="col">Кто</th>
              <th scope="col">Действие</th>
              <th scope="col">Объект</th>
              <th scope="col">Итог</th>
              <th scope="col">Адрес</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.created_at}-${i}`}>
                <td className="mono">{new Date(r.created_at).toLocaleString("ru-RU")}</td>
                <td className="mono">{r.login || "—"}</td>
                <td>{action(r.method, r.path)}</td>
                <td className="mono">{r.path.replace(/^\/api\//, "")}</td>
                <td>{r.status < 400 ? "успешно" : <span className="error">отказ {r.status}</span>}</td>
                <td className="mono">{r.client}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
