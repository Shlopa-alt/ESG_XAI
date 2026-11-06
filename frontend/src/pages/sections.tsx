import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { listDatasets, listExperiments, OUTCOME_LABEL } from "../api/experiments";
import { listHypotheses } from "../api/hypotheses";
import { CORPUS, CORPUS_TOTAL } from "../content";
import { useMe } from "../auth/useAuth";
import { NewDataset } from "./DatasetPage";
import { KbLive } from "./KbLive";
import { LAB, ORG } from "../org";
import { BankTabs, DataTabs } from "../components/SectionTabs";
import { canReview, canRun, plural } from "../components/Ux";

function Head({ eyebrow, title, lead }: { eyebrow: string; title: string; lead: string }) {
  return (
    <section className="page-head">
      <span className="eyebrow">{eyebrow}</span>
      <h1 className="page-title">{title}</h1>
      <p className="lead">{lead}</p>
    </section>
  );
}

const fmt = (n: number) => n.toLocaleString("ru-RU");

export function Overview() {
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const hyps = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const role = useMe().data?.role;
  const experiments = Array.isArray(exps.data) ? exps.data : [];
  const ideas = Array.isArray(hyps.data) ? hyps.data : [];
  const found = experiments.filter((e) => e.outcome).slice(0, 3);
  const waiting = ideas.filter((h) => h.status === "proposed").length;
  const accepted = ideas.filter((h) => h.status === "accepted").length;
  const inReview = experiments.filter((e) => e.status === "review").length;
  return (
    <>
      <section className="hero">
        <span className="hero-kicker">
          {ORG} · {LAB}
        </span>
        <h1 className="hero-title">Проверяем на данных, окупается ли забота о природе и людях</h1>
        <p className="hero-lead">
          Компании и регионы вкладываются в экологию, условия труда и честное управление. Мы собираем научные статьи,
          формулируем идеи и считаем, что подтверждается, а что нет. Результат публикуем, даже если идея не подтвердилась.
        </p>
        <div className="hero-actions">
          <a href="#found" className="btn-hero">
            Что уже выяснили
          </a>
          <Link to="/methodology" className="btn-hero-ghost">
            Как мы исследуем
          </Link>
        </div>
      </section>

      <section className="overview-block" aria-labelledby="what-esg">
        <h2 className="h2" id="what-esg">
          Что такое ESG
        </h2>
        <p className="overview-text">
          Три буквы означают три вопроса к компании или региону: как они обращаются с природой, с людьми и со своими
          решениями. Ответ важен не только для сегодняшней прибыли, но и для устойчивости на годы вперёд.
        </p>
        <ul className="esg-grid">
          <li className="card">
            <span className="esg-letter">E</span>
            <strong>Экология</strong>
            <span className="muted">Выбросы, энергия, вода, отходы, влияние на климат</span>
          </li>
          <li className="card">
            <span className="esg-letter">S</span>
            <strong>Общество</strong>
            <span className="muted">Условия и оплата труда, безопасность, отношения с людьми вокруг</span>
          </li>
          <li className="card">
            <span className="esg-letter">G</span>
            <strong>Управление</strong>
            <span className="muted">Прозрачная отчётность, борьба с коррупцией, работа совета директоров</span>
          </li>
        </ul>
      </section>

      <section className="overview-block" id="found" aria-labelledby="found-title">
        <h2 className="h2" id="found-title">
          Что уже выяснили
        </h2>
        {exps.isPending && <p className="muted">Загрузка…</p>}
        {exps.isError && (
          <p className="error" role="alert">
            Не удалось загрузить результаты: {exps.error.message}
          </p>
        )}
        {exps.isSuccess && found.length === 0 && <p className="muted">Законченных проверок пока нет. Их итоги появятся здесь.</p>}
        <div className="found-grid">
          {found.map((e) => (
            <article key={e.code} className="card found-card">
              <div className="kb-meta">
                <span className={`badge ${e.outcome === "confirmed" ? "st-done" : "st-planned"}`}>{e.outcome && OUTCOME_LABEL[e.outcome]}</span>
                {e.status === "review" && <span className="muted">ещё на рецензии</span>}
              </div>
              <h3 className="h3">
                <Link to={`/experiments/${e.code}`}>{e.title}</Link>
              </h3>
              {e.conclusion && <p className="muted">{e.conclusion.length > 240 ? `${e.conclusion.slice(0, 240).replace(/\s+\S*$/, "")}…` : e.conclusion}</p>}
            </article>
          ))}
        </div>
        {found.length > 0 && (
          <p className="muted">Отрицательный результат здесь такая же находка, как и положительный: он показывает, на что нельзя опираться.</p>
        )}
      </section>

      <section className="overview-block" aria-labelledby="start-title">
        <h2 className="h2" id="start-title">
          С чего начать
        </h2>
        <div className="start-grid">
          <Link to="/knowledge" className="card start-card">
            <strong>Почитать, что известно</strong>
            <span className="muted">Спросите своими словами в банке статей: русский запрос найдёт и английские статьи</span>
          </Link>
          <Link to="/hypotheses" className="card start-card">
            <strong>Предложить свою идею</strong>
            <span className="muted">Любой участник может предложить, что стоит проверить</span>
          </Link>
          <Link to="/experiments" className="card start-card">
            <strong>Посмотреть все проверки</strong>
            <span className="muted">Что считали, на каких данных и чем закончилось</span>
          </Link>
        </div>
        {(canReview(role) && waiting > 0) || (canRun(role) && accepted > 0) || (canReview(role) && inReview > 0) ? (
          <ul className="todo-list">
            {canReview(role) && waiting > 0 && (
              <li>
                <Link to="/hypotheses">Ждут вашего решения: {plural(waiting, "идея", "идеи", "идей")}</Link>
              </li>
            )}
            {canRun(role) && accepted > 0 && (
              <li>
                <Link to="/run">Можно проверить: {plural(accepted, "принятая идея", "принятые идеи", "принятых идей")}</Link>
              </li>
            )}
            {canReview(role) && inReview > 0 && (
              <li>
                <Link to="/experiments">Ждут рецензии: {plural(inReview, "проверка", "проверки", "проверок")}</Link>
              </li>
            )}
          </ul>
        ) : null}
      </section>
    </>
  );
}

export function Knowledge() {
  return (
    <>
      <Head eyebrow="БАНК СТАТЕЙ" title="Банк статей" lead="Научные статьи об ESG, на которые мы опираемся. Спросите своими словами, русский запрос найдёт и английские статьи." />
      <BankTabs />
      <KbLive />
      <details className="card details-card">
        <summary>Что ещё будет в банке: {fmt(CORPUS_TOTAL)} собранных статей</summary>
        <p className="muted">
          Статьи открытого доступа, 2018 г. и новее (OpenAlex, DOAJ, КиберЛенинка). Они загружаются по темам.
        </p>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Тема</th>
                <th scope="col" className="num">
                  Статей
                </th>
              </tr>
            </thead>
            <tbody>
              {CORPUS.map((g) => (
                <tr key={g.name}>
                  <td>{g.name}</td>
                  <td className="num mono">{fmt(g.count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

export function Data() {
  const ds = useQuery({ queryKey: ["datasets"], queryFn: listDatasets });
  const me = useMe();
  const canCreate = me.data?.role === "researcher" || me.data?.role === "owner";
  const [creating, setCreating] = useState(false);
  const datasets = Array.isArray(ds.data) ? ds.data : [];
  return (
    <>
      <Head eyebrow="ДАННЫЕ" title="Данные" lead="Таблицы показателей компаний и регионов, на которых считаются проверки. Данные под NDA видны только тем, у кого есть допуск." />
      <DataTabs />
      {canCreate && !creating && (
        <div>
          <button type="button" className="btn-ghost" onClick={() => setCreating(true)}>
            Новый набор данных
          </button>
        </div>
      )}
      {creating && <NewDataset onDone={() => setCreating(false)} />}
      {ds.isError && (
        <p className="error" role="alert">
          Не удалось загрузить данные: {ds.error.message}
        </p>
      )}
      {ds.isSuccess && datasets.length === 0 && <p className="muted">Наборов данных пока нет.</p>}
      {datasets.length > 0 && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Код</th>
                <th scope="col">Набор данных</th>
                <th scope="col">Доступ</th>
                <th scope="col">Источник</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.code}>
                  <td className="mono">
                    <Link to={`/datasets/${d.code}`}>{d.code}</Link>
                  </td>
                  <td>
                    <strong>{d.title}</strong>
                    <div className="muted clamp-2">{d.description}</div>
                  </td>
                  <td>{d.access_level === "nda" ? <span className="badge st-review">NDA</span> : "открытый"}</td>
                  <td>
                    {d.source_url.startsWith("http") ? (
                      <a href={d.source_url} target="_blank" rel="noreferrer">
                        ссылка
                      </a>
                    ) : (
                      <span className="muted">{d.source_url || "—"}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
