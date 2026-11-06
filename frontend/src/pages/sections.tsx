import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { listDatasets, listExperiments, OUTCOME_LABEL } from "../api/experiments";
import { listHypotheses } from "../api/hypotheses";
import { kbDocuments, kbStats } from "../api/kb";
import { listCrs } from "../api/methodology";
import { useMe } from "../auth/useAuth";
import { NewDataset } from "./DatasetPage";
import { KbLive } from "./KbLive";
import { ORG, WITH_LAB } from "../org";
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

const fmt = (n: number | undefined) => (n ?? 0).toLocaleString("ru-RU");

/** Плитка-счётчик: число и что оно значит, нажатие ведёт в раздел. */
function Tile({ to, value, label, note }: { to: string; value: string; label: string; note?: string }) {
  return (
    <Link to={to} className="card tile">
      <span className="tile-value">{value}</span>
      <span className="tile-label">{label}</span>
      {note && <span className="muted tile-note">{note}</span>}
    </Link>
  );
}

/** Слово в нужной форме: 1 статья, 2 статьи, 5 статей. */
const word = (n: number, one: string, few: string, many: string) => plural(n, one, few, many).replace(/^\S+\s/, "");

const GLOSSARY: Array<[string, string]> = [
  ["ESG", "Экология, общество и управление: как компания или регион обращается с природой, людьми и своими решениями."],
  ["Идея для проверки", "Утверждение, которое можно подтвердить или опровергнуть расчётом. В науке его называют гипотезой."],
  ["Проверка", "Расчёт на конкретных данных и отчёт о нём: подтвердилась ли идея."],
  ["Источник", "Цитата из научной статьи, на которой держится идея. Её всегда можно открыть и прочитать."],
  ["Методика", "Что изучает лаборатория и по каким правилам. Меняется только с основанием и после рецензии."],
  ["Рецензия", "Другой человек проверяет работу, прежде чем её примут."],
  ["ИИ-помощник", "Языковая модель лаборатории. Предлагает идеи и пишет черновики отчётов, а решения принимают люди."],
];

export function Overview() {
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const hyps = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const crs = useQuery({ queryKey: ["crs"], queryFn: listCrs });
  const ds = useQuery({ queryKey: ["datasets"], queryFn: listDatasets });
  const kb = useQuery({ queryKey: ["kb", "stats", "esg"], queryFn: () => kbStats("esg") });
  const lab = useQuery({ queryKey: ["kb", "docs", "esg.lab"], queryFn: () => kbDocuments("esg.lab") });
  const role = useMe().data?.role;
  const experiments = Array.isArray(exps.data) ? exps.data : [];
  const ideas = Array.isArray(hyps.data) ? hyps.data : [];
  const datasets = Array.isArray(ds.data) ? ds.data : [];
  const labDocs = Array.isArray(lab.data) ? lab.data : [];
  const proposals = Array.isArray(crs.data) ? crs.data.filter((c) => c.status === "proposed" || c.status === "review") : [];
  const found = experiments.filter((e) => e.outcome).slice(0, 4);
  const waiting = ideas.filter((h) => h.status === "proposed").length;
  const accepted = ideas.filter((h) => h.status === "accepted").length;
  const inReview = experiments.filter((e) => e.status === "review").length;
  const withFiles = datasets.filter((d) => (d.snapshots ?? 0) > 0).length;
  return (
    <>
      <section className="hero">
        <span className="hero-kicker">
          {ORG} {WITH_LAB}
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

      <section className="tiles" aria-label="Что уже есть на платформе">
        <Tile to="/knowledge" value={kb.data ? fmt(kb.data.documents) : "—"} label={`${word(kb.data?.documents ?? 0, "статья", "статьи", "статей")} в банке`} note={kb.data?.year_from ? `${kb.data.year_from}–${kb.data.year_to} годы` : undefined} />
        <Tile to="/knowledge/graph" value={kb.data?.facts !== undefined ? fmt(kb.data.facts) : "—"} label={`${word(kb.data?.facts ?? 0, "утверждение", "утверждения", "утверждений")} с цитатами`} note="на карте связей" />
        <Tile to="/hypotheses" value={fmt(ideas.length)} label={`${word(ideas.length, "идея", "идеи", "идей")} для проверки`} note={waiting ? `ждут решения: ${waiting}` : undefined} />
        <Tile to="/experiments" value={fmt(experiments.length)} label={word(experiments.length, "проверка", "проверки", "проверок")} note={inReview ? `на рецензии: ${inReview}` : undefined} />
        <Tile to="/data" value={fmt(datasets.length)} label={`${word(datasets.length, "набор", "набора", "наборов")} данных`} note={datasets.length ? `с файлами: ${withFiles}` : undefined} />
        <Tile to="/methodology" value={fmt(proposals.length)} label={word(proposals.length, "открытое предложение", "открытых предложения", "открытых предложений")} note="изменить методику" />
      </section>

      <section className="overview-block" aria-labelledby="what-esg">
        <h2 className="h2" id="what-esg">
          Что такое ESG
        </h2>
        <p className="overview-text">
          ESG — это три вопроса к компании или региону: как они обращаются с природой, с людьми и со своими решениями. Ответ
          важен не только для сегодняшней прибыли, но и для устойчивости на годы вперёд. По этим вопросам компании оценивают
          рейтинговые агентства, инвесторы и государство.
        </p>
        <ul className="esg-grid">
          <li className="card">
            <span className="esg-letter">E</span>
            <strong>Экология</strong>
            <span className="muted">Выбросы, энергия, вода, отходы, влияние на климат и природу вокруг</span>
          </li>
          <li className="card">
            <span className="esg-letter">S</span>
            <strong>Общество</strong>
            <span className="muted">Условия и оплата труда, безопасность, отношения с клиентами и людьми вокруг</span>
          </li>
          <li className="card">
            <span className="esg-letter">G</span>
            <strong>Управление</strong>
            <span className="muted">Прозрачная отчётность, борьба с коррупцией, работа совета директоров</span>
          </li>
        </ul>
        <p className="overview-text">
          Проблема в том, что разные агентства часто оценивают одну и ту же компанию по-разному, а компании и регионы не знают,
          какие вложения действительно окупаются. Отзывы и обещания здесь не помогают: нужны расчёты на настоящих данных.
        </p>
      </section>

      <section className="overview-block" aria-labelledby="study-title">
        <h2 className="h2" id="study-title">
          Что мы изучаем
        </h2>
        <div className="two-grid">
          <article className="card study-card">
            <span className="eyebrow">НАПРАВЛЕНИЕ 1</span>
            <h3 className="h3">Какие ESG-вложения окупаются</h3>
            <p>
              Строим нейросетевую модель, которая связывает вложения в разные статьи ESG с результатами через несколько лет:
              у самой компании, в бюджете её региона и в федеральном бюджете. Цель — подсказка для решения, во что вкладывать
              целесообразно, а во что нет.
            </p>
            <Link to="/methodology">Посмотреть задания</Link>
          </article>
          <article className="card study-card">
            <span className="eyebrow">НАПРАВЛЕНИЕ 2</span>
            <h3 className="h3">Можно ли доверять ESG-рейтингам</h3>
            <p>
              Сравниваем, насколько согласуются оценки разных рейтинговых агентств, и разбираем, по каким критериям и с какими
              весами считают рейтинги российские агентства.
            </p>
            <Link to="/methodology">Посмотреть задания</Link>
          </article>
        </div>
      </section>

      <section className="overview-block" aria-labelledby="how-title">
        <h2 className="h2" id="how-title">
          Как мы работаем
        </h2>
        <ol className="how-steps">
          <li className="card">
            <strong>Изучаем статьи</strong>
            <span className="muted">Собираем научные статьи и разбираем их. ИИ-помощник выписывает утверждения с цитатами.</span>
            <Link to="/knowledge">Банк статей</Link>
          </li>
          <li className="card">
            <strong>Предлагаем идеи</strong>
            <span className="muted">Человек или ИИ-помощник формулирует, что стоит проверить. Рецензент решает, брать ли идею в работу.</span>
            <Link to="/hypotheses">Идеи для проверки</Link>
          </li>
          <li className="card">
            <strong>Проверяем на данных</strong>
            <span className="muted">Заранее записываем, что подтвердит идею, считаем и пишем отчёт. Рецензент его читает.</span>
            <Link to="/experiments">Проверки</Link>
          </li>
          <li className="card">
            <strong>Уточняем методику</strong>
            <span className="muted">Если результат что-то меняет, появляется предложение изменить методику, и его тоже рецензируют.</span>
            <Link to="/methodology">Методика</Link>
          </li>
        </ol>
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
              {e.conclusion && <p className="muted">{e.conclusion.length > 260 ? `${e.conclusion.slice(0, 260).replace(/\s+\S*$/, "")}…` : e.conclusion}</p>}
            </article>
          ))}
        </div>
        {found.length > 0 && (
          <p className="muted">Отрицательный результат здесь такая же находка, как и положительный: он показывает, на что нельзя опираться.</p>
        )}
      </section>

      <section className="overview-block" aria-labelledby="trust-title">
        <h2 className="h2" id="trust-title">
          Почему этому можно доверять
        </h2>
        <ul className="trust-grid">
          <li>
            <strong>У каждого утверждения есть цитата.</strong> Его можно открыть в статье и проверить самому.
          </li>
          <li>
            <strong>Любой расчёт можно повторить.</strong> Записаны версия данных, код и настройки, поэтому другой человек получит те же числа.
          </li>
          <li>
            <strong>Что считать успехом, решаем заранее.</strong> Критерий записывается до расчёта, чтобы результат нельзя было подогнать.
          </li>
          <li>
            <strong>Отрицательные результаты публикуются</strong> наравне с положительными, а не прячутся.
          </li>
          <li>
            <strong>Решают люди.</strong> ИИ-помощник только предлагает: идеи, отчёты и изменения методики принимают рецензенты.
          </li>
        </ul>
      </section>

      {labDocs.length > 0 && (
        <section className="overview-block" aria-labelledby="lab-title">
          <h2 className="h2" id="lab-title">
            Материалы лаборатории
          </h2>
          <ul className="list card">
            {labDocs.map((d) => (
              <li key={d.doc_id}>
                <Link to={`/knowledge/article/${encodeURIComponent(d.doc_id)}`}>{d.title || d.doc_id}</Link>
                {d.year && <span className="muted"> · {d.year}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="overview-block" aria-labelledby="words-title">
        <h2 className="h2" id="words-title">
          Основные слова
        </h2>
        <dl className="glossary card">
          {GLOSSARY.map(([term, text]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd className="muted">{text}</dd>
            </div>
          ))}
        </dl>
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
          <Link to="/knowledge/graph" className="card start-card">
            <strong>Посмотреть карту связей</strong>
            <span className="muted">Что влияет на стоимость компании, прибыль или рейтинги, и какие статьи это подтверждают</span>
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
          <div className="card your-tasks">
            <h3 className="h3">Ждёт вас</h3>
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
          </div>
        ) : null}
      </section>
    </>
  );
}

export function Knowledge() {
  return (
    <>
      <Head
        eyebrow="БАНК СТАТЕЙ"
        title="Банк статей"
        lead="Научные статьи об ESG, на которые опираются наши исследования. Каждая разобрана на отрывки, поэтому поиск находит конкретное место в статье, а русский запрос находит и английские тексты."
      />
      <BankTabs />
      <KbLive />
    </>
  );
}

export function Data() {
  const ds = useQuery({ queryKey: ["datasets"], queryFn: listDatasets });
  const me = useMe();
  const canCreate = me.data?.role === "researcher" || me.data?.role === "owner";
  const [creating, setCreating] = useState(false);
  const datasets = Array.isArray(ds.data) ? ds.data : [];
  const withFiles = datasets.filter((d) => (d.snapshots ?? 0) > 0).length;
  return (
    <>
      <Head
        eyebrow="ДАННЫЕ"
        title="Данные"
        lead="Таблицы показателей компаний и регионов, на которых считаются проверки. У каждого набора записан источник, а каждая версия файла зафиксирована: расчёт всегда можно повторить на тех же данных."
      />
      <DataTabs />
      {ds.isSuccess && datasets.length > 0 && (
        <p className="overview-text">
          Заведено наборов: {datasets.length}, с загруженными файлами: {withFiles}. Ещё больше данных можно получить из таблиц в
          статьях банка: смотрите вкладку <Link to="/data-drafts">«Данные из статей»</Link>.
        </p>
      )}
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
                <th scope="col">Файлы</th>
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
                  <td>
                    {(d.snapshots ?? 0) > 0 ? (
                      plural(d.snapshots ?? 0, "версия", "версии", "версий")
                    ) : (
                      <span className="badge st-planned">пока нет</span>
                    )}
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
