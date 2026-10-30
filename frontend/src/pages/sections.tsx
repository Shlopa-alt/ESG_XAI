import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  CARDS,
  CHANGE_REQUESTS,
  CORPUS,
  CORPUS_TOTAL,
  type CardType,
  EXPERIMENTS,
  LAB_FILES,
  METHODOLOGY_VERSION,
  OUTCOME_LABEL,
  SECTIONS,
  STABILITY_LABEL,
  STATUS_LABEL,
  TYPE_LABEL,
} from "../content";
import { KbGraphSummary, KbLive } from "./KbLive";
import { SectionPage } from "./SectionPage";

function Head({ eyebrow, title, lead }: { eyebrow: string; title: string; lead: string }) {
  return (
    <section className="page-head">
      <span className="eyebrow">{eyebrow}</span>
      <h1 className="page-title">{title}</h1>
      <p className="lead">{lead}</p>
    </section>
  );
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="card stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

const fmt = (n: number) => n.toLocaleString("ru-RU");

export const Overview = () => (
  <>
    <Head
      eyebrow="ЛАБОРАТОРИЯ · ИНС В ESG-УПРАВЛЕНИИ"
      title="Открытые исследования ESG"
      lead="Методология дорабатывается по циклу: источник в базе знаний порождает гипотезу, гипотеза проверяется экспериментом, а результат становится обоснованием изменения методологии."
    />
    <div className="stats">
      <Stat value={fmt(CORPUS_TOTAL)} label="статей в корпусе базы знаний" />
      <Stat value={CARDS.length} label="карточек: статьи, методы, датасеты, стандарты" />
      <Stat value={EXPERIMENTS.length} label="эксперимента в реестре" />
      <Stat value={CHANGE_REQUESTS.length} label="предложение изменения методологии" />
    </div>
    <div className="grid-2">
      <section className="card">
        <h2 className="h2">Последние эксперименты</h2>
        <ul className="list">
          {EXPERIMENTS.map((e) => (
            <li key={e.code}>
              <Link to={`/experiments/${e.code}`} className="mono">{e.code}</Link> {e.title}
              <div className="muted">
                <span className={`badge st-${e.status}`}>{STATUS_LABEL[e.status]}</span>{" "}
                {e.outcome && OUTCOME_LABEL[e.outcome]}
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="card">
        <h2 className="h2">Открытые вопросы методологии</h2>
        <ul className="list">
          {SECTIONS.filter((s) => s.stability !== "stable").map((s) => (
            <li key={s.number}>
              <strong>{s.number}.</strong> {s.title}
              <div className="muted">{STABILITY_LABEL[s.stability]}</div>
            </li>
          ))}
        </ul>
      </section>
    </div>
    <section className="card">
      <h2 className="h2">Новое в базе знаний: материалы лаборатории</h2>
      <ul className="list">
        {LAB_FILES.map((f) => (
          <li key={f.title}>
            {f.title}
            <div className="muted">{f.note}</div>
          </li>
        ))}
      </ul>
    </section>
  </>
);

const FILTERS: Array<{ key: CardType | "all"; label: string }> = [
  { key: "all", label: "Все" },
  { key: "article", label: "Статьи" },
  { key: "method", label: "Методы" },
  { key: "dataset", label: "Датасеты" },
  { key: "standard", label: "Стандарты" },
];

export function Knowledge() {
  const [type, setType] = useState<CardType | "all">("all");
  const [selected, setSelected] = useState(CARDS[0].code);
  const cards = CARDS.filter((c) => type === "all" || c.type === type);
  const card = CARDS.find((c) => c.code === selected) ?? CARDS[0];
  return (
    <>
      <Head
        eyebrow="БАЗА ЗНАНИЙ"
        title="База знаний"
        lead="Статьи корпуса разобраны в базе знаний KBRAG: поиск по смыслу и по словам, русский запрос находит и английские статьи. Ниже — паспорта материалов и датасетов лаборатории."
      />
      <KbLive />
      <h2 className="h2">Материалы и датасеты лаборатории</h2>
      <div className="filters" role="group" aria-label="Тип карточки">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={type === f.key ? "chip active" : "chip"}
            aria-pressed={type === f.key}
            onClick={() => setType(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="grid-kb">
        <ul className="cards">
          {cards.map((c) => (
            <li key={c.code}>
              <button
                type="button"
                className={c.code === card.code ? "card kb-card active" : "card kb-card"}
                onClick={() => setSelected(c.code)}
              >
                <span className="kb-meta">
                  <span className="mono">{c.code}</span> · {TYPE_LABEL[c.type]} · {c.direction}
                  {!c.verified && <span className="badge st-review">требует источника</span>}
                </span>
                <span className="kb-title">{c.title}</span>
              </button>
            </li>
          ))}
        </ul>
        <aside className="card passport" aria-label="Паспорт карточки">
          <span className="eyebrow">ПАСПОРТ · {card.code}</span>
          <h2 className="h2">{card.title}</h2>
          <p>{card.summary}</p>
          <dl className="dl">
            <dt>Тип</dt>
            <dd>{TYPE_LABEL[card.type]}</dd>
            <dt>Направление</dt>
            <dd>{card.direction}</dd>
            <dt>Источник</dt>
            <dd>{card.source}</dd>
            <dt>Источник проверен</dt>
            <dd>{card.verified ? "да" : "нет"}</dd>
            <dt>Связи</dt>
            <dd>{card.links.length ? card.links.join(", ") : "—"}</dd>
          </dl>
        </aside>
      </div>
      <section className="card">
        <h2 className="h2">Корпус статей: {fmt(CORPUS_TOTAL)} PDF</h2>
        <p className="muted">
          Открытый доступ, 2018 г. и новее; источники OpenAlex, DOAJ, КиберЛенинка. Пилот базы знаний — 296 статей
          по направлениям 1–2 и материалы лаборатории.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Направление</th>
              <th scope="col" className="num">Статей</th>
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
      </section>
    </>
  );
}

export const Graph = () => (
  <>
    <Head
      eyebrow="БАЗА ЗНАНИЙ · ГРАФ"
      title="Граф связей"
      lead="Граф фактов из статей строится в базе знаний KBRAG по правилам ветки esg: ESG-фактор → механизм влияния → финансовый результат. Каждый факт — с дословной цитатой из статьи."
    />
    <KbGraphSummary />
  </>
);

export const Experiments = () => (
  <>
    <Head
      eyebrow="ЭКСПЕРИМЕНТЫ"
      title="Реестр экспериментов"
      lead="Воспроизводимые запуски: версия данных, код, окружение, метрики. Отрицательные результаты публикуются наравне с положительными."
    />
    <div className="card table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Код</th>
            <th scope="col">Эксперимент</th>
            <th scope="col">Направление</th>
            <th scope="col">Статус</th>
            <th scope="col">Данные</th>
            <th scope="col">Итог</th>
            <th scope="col">CR</th>
          </tr>
        </thead>
        <tbody>
          {EXPERIMENTS.map((e) => (
            <tr key={e.code}>
              <td><Link to={`/experiments/${e.code}`} className="mono">{e.code}</Link></td>
              <td>{e.title}</td>
              <td>{e.direction}</td>
              <td><span className={`badge st-${e.status}`}>{STATUS_LABEL[e.status]}</span></td>
              <td>{e.data}</td>
              <td>{e.outcome ? OUTCOME_LABEL[e.outcome] : "—"}</td>
              <td className="mono">{e.cr}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </>
);

function Block({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="card">
      <h2 className="h2">{title}</h2>
      <ul className="list">
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </section>
  );
}

export function Experiment() {
  const { code } = useParams();
  const e = EXPERIMENTS.find((x) => x.code === code);
  if (!e) {
    return (
      <SectionPage eyebrow="ЭКСПЕРИМЕНТЫ" title="Эксперимент не найден" lead={`Нет эксперимента с кодом ${code ?? ""}.`} />
    );
  }
  return (
    <>
      <div className="muted">
        <Link to="/experiments">Эксперименты</Link> / <span className="mono">{e.code}</span>
      </div>
      <Head eyebrow={`${e.code} · ${e.direction}`} title={e.title} lead={e.data} />
      <div>
        <span className={`badge st-${e.status}`}>{STATUS_LABEL[e.status]}</span>{" "}
        {e.outcome && <span className="badge st-planned">{OUTCOME_LABEL[e.outcome]}</span>}
      </div>
      <section className="card">
        <h2 className="h2">Гипотеза</h2>
        <p>{e.hypothesis}</p>
      </section>
      <Block title="Постановка" items={e.setup} />
      <Block title="Результат" items={e.result} />
      <section className="card accent">
        <h2 className="h2">Вывод</h2>
        <p>{e.conclusion}</p>
        {e.cr !== "—" && (
          <p className="muted">
            Влияние на методологию: <Link to="/methodology" className="mono">{e.cr}</Link>
          </p>
        )}
      </section>
      <div className="grid-2">
        <Block title="Ограничения" items={e.limitations} />
        <Block title="Воспроизводимость" items={e.reproducibility} />
      </div>
    </>
  );
}

export const Run = () => (
  <SectionPage
    eyebrow="ЭКСПЕРИМЕНТЫ · ЗАПУСК"
    title="Запуск экспериментов"
    lead="Конфигурация запуска, живой поток метрик и логов, очередь сервера. Скрипты EXP-007 уже лежат в runner/hsu2025."
  />
);

export const Methodology = () => (
  <>
    <Head
      eyebrow={`МЕТОДОЛОГИЯ · ВЕРСИЯ ${METHODOLOGY_VERSION}`}
      title="Методология"
      lead="Разделы по постановке задачи лаборатории для ИНС, их устойчивость и предложения изменений."
    />
    <div className="grid-2">
      <section className="card">
        <h2 className="h2">Разделы</h2>
        <ol className="list">
          {SECTIONS.map((s) => (
            <li key={s.number}>
              <strong>{s.title}</strong>{" "}
              <span className={`badge stab-${s.stability}`}>{STABILITY_LABEL[s.stability]}</span>
              <p className="muted">{s.text}</p>
            </li>
          ))}
        </ol>
      </section>
      <section className="card">
        <h2 className="h2">Предложения изменений (CR)</h2>
        <ul className="list">
          {CHANGE_REQUESTS.map((cr) => (
            <li key={cr.code}>
              <span className="mono">{cr.code}</span> · раздел {cr.section}: {cr.title}
              <div className="muted">
                <span className="badge st-planned">предложено</span> основание:{" "}
                <Link to={`/experiments/${cr.basis}`} className="mono">{cr.basis}</Link>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  </>
);
