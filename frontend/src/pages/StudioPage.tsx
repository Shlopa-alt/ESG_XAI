import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createScenario, listScenarios } from "../api/studio";
import { useMe } from "../auth/useAuth";

const day = (iso: string) => new Date(iso).toLocaleDateString("ru-RU");

/** Студия: список сценариев и новый сценарий. Сам редактор — StudioEditor (грузится отдельно). */
export function Studio() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const me = useMe();
  const canEdit = me.data?.role !== "reader" && me.data?.role !== "reviewer";
  const list = useQuery({ queryKey: ["studio", "list"], queryFn: listScenarios });
  const [title, setTitle] = useState("");
  const create = useMutation({
    mutationFn: () => createScenario(title.trim()),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["studio", "list"] });
      navigate(`/studio/${s.code}`);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  const rows = Array.isArray(list.data) ? list.data : [];

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">ИНСТРУМЕНТЫ</span>
        <h1 className="page-title">Студия анализа</h1>
        <p className="lead">
          Сценарии обработки и анализа данных из узлов, как в Loginom: загрузите набор, соберите цепочку — фильтр,
          группировка, слияние, формулы — и смотрите результат каждого узла. Расчёт идёт на компьютере лаборатории и
          записывается так, чтобы его можно было повторить.
        </p>
      </section>
      {canEdit && (
        <form className="card user-form" onSubmit={submit}>
          <h2 className="h2">Новый сценарий</h2>
          <label className="field inline grow">
            Название
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="например, отрасли и рентабельность" required maxLength={256} />
          </label>
          <button type="submit" className="btn-primary" disabled={create.isPending}>
            Создать
          </button>
          {create.isError && (
            <p className="error" role="alert">
              {create.error.message}
            </p>
          )}
        </form>
      )}
      <section className="card table-wrap">
        <h2 className="h2">Сценарии</h2>
        {list.isPending ? (
          <p className="empty">Загрузка…</p>
        ) : rows.length === 0 ? (
          <p className="empty">Сценариев пока нет.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Код</th>
                <th scope="col">Название</th>
                <th scope="col">Автор</th>
                <th scope="col" className="num">Узлов</th>
                <th scope="col" className="num">Версия</th>
                <th scope="col">Изменён</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.code}>
                  <td className="mono">
                    <Link to={`/studio/${s.code}`}>{s.code}</Link>
                  </td>
                  <td>
                    <Link to={`/studio/${s.code}`}>{s.title}</Link>
                  </td>
                  <td className="mono">{s.author}</td>
                  <td className="num">{s.nodes}</td>
                  <td className="num">{s.version}</td>
                  <td>{day(s.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
