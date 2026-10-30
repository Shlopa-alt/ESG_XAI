import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listDatasets, listExperiments, OUTCOME_LABEL, STATUS_LABEL } from "../api/experiments";
import { listHypotheses } from "../api/hypotheses";
import { kbDocuments, kbStats } from "../api/kb";
import { getMethodology, listCrs, STABILITY_LABEL } from "../api/methodology";
import { CORPUS, CORPUS_TOTAL } from "../content";
import { KbLive } from "./KbLive";

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

export function Overview() {
  const exps = useQuery({ queryKey: ["experiments"], queryFn: listExperiments });
  const meth = useQuery({ queryKey: ["methodology"], queryFn: getMethodology });
  const crs = useQuery({ queryKey: ["crs"], queryFn: listCrs });
  const hyps = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const kb = useQuery({ queryKey: ["kb", "stats", "esg"], queryFn: () => kbStats("esg") });
  const lab = useQuery({ queryKey: ["kb", "docs", "esg.lab"], queryFn: () => kbDocuments("esg.lab") });
  const experiments = Array.isArray(exps.data) ? exps.data : [];
  const sections = Array.isArray(meth.data?.sections) ? meth.data.sections : [];
  const openCrs = Array.isArray(crs.data) ? crs.data.filter((c) => c.status === "proposed" || c.status === "review") : [];
  const waiting = Array.isArray(hyps.data) ? hyps.data.filter((h) => h.status === "proposed").length : 0;
  const labDocs = Array.isArray(lab.data) ? lab.data : [];
  return (
    <>
      <Head
        eyebrow="ЛАБОРАТОРИЯ · ИНС В ESG-УПРАВЛЕНИИ"
        title="Открытые исследования ESG"
        lead="Методология дорабатывается по циклу: источник в базе знаний порождает гипотезу, гипотеза проверяется экспериментом, а результат становится обоснованием изменения методологии."
      />
      <div className="stats">
        <Stat value={kb.data ? fmt(kb.data.documents) : "—"} label="статей в базе знаний" />
        <Stat value={waiting} label="гипотез ждут решения" />
        <Stat value={experiments.length} label="экспериментов в реестре" />
        <Stat value={openCrs.length} label="открытых предложений изменения методологии" />
      </div>
      <div className="grid-2">
        <section className="card">
          <h2 className="h2">Последние эксперименты</h2>
          <ul className="list">
            {experiments.map((e) => (
              <li key={e.code}>
                <Link to={`/experiments/${e.code}`} className="mono">
                  {e.code}
                </Link>{" "}
                {e.title}
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
            {sections
              .filter((s) => s.stability !== "stable")
              .map((s) => (
                <li key={s.number}>
                  <strong>{s.number}.</strong> {s.title}
                  <div className="muted">{STABILITY_LABEL[s.stability]}</div>
                </li>
              ))}
          </ul>
        </section>
      </div>
      <section className="card">
        <h2 className="h2">Материалы лаборатории в базе знаний</h2>
        {lab.isError && <p className="muted">База знаний сейчас недоступна.</p>}
        <ul className="list">
          {labDocs.map((d) => (
            <li key={d.doc_id}>
              <Link to={`/knowledge/article/${encodeURIComponent(d.doc_id)}`}>{d.title || d.doc_id}</Link>
              <div className="muted">
                {d.year ?? "—"} · {d.chunks} фрагментов
              </div>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export function Knowledge() {
  const ds = useQuery({ queryKey: ["datasets"], queryFn: listDatasets });
  const datasets = Array.isArray(ds.data) ? ds.data : [];
  return (
    <>
      <Head
        eyebrow="БАЗА ЗНАНИЙ"
        title="База знаний"
        lead="Статьи корпуса и материалы лаборатории разобраны в базе знаний KBRAG: поиск по смыслу и по словам, русский запрос находит и английские статьи. Из найденной статьи можно предложить гипотезу или сослаться на неё в эксперименте."
      />
      <KbLive />
      <section className="card">
        <h2 className="h2">Датасеты</h2>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Код</th>
                <th scope="col">Датасет</th>
                <th scope="col">Доступ</th>
                <th scope="col">Источник</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.code}>
                  <td className="mono">{d.code}</td>
                  <td>
                    <strong>{d.title}</strong>
                    <div className="muted">{d.description}</div>
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
      </section>
      <section className="card">
        <h2 className="h2">Корпус для загрузки: {fmt(CORPUS_TOTAL)} PDF</h2>
        <p className="muted">
          Собранные статьи открытого доступа (2018 г. и новее; OpenAlex, DOAJ, КиберЛенинка). В базе знаний пока пилот —
          около 300 статей по направлениям 1–2 и материалы лаборатории; остальное загружается по веткам.
        </p>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Направление</th>
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
      </section>
    </>
  );
}

