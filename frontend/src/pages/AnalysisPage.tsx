import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { getCatalog, launchAnalysis, recommend, type Recommendation, type RecommendOut } from "../api/analysis";
import { listHypotheses } from "../api/hypotheses";
import { useMe } from "../auth/useAuth";
import { NodeSelect } from "../components/NodeSelect";
import { defaults, ParamsEditor, type ParamValue } from "../components/ParamsEditor";
import { RunCost } from "../components/RunCost";
import { canRun, NextStep } from "../components/Ux";
import { listTemplates, type RunTemplate } from "./RunPage";

/** Карточка рекомендации: метод и сеть, почему, параметры, запуск. */
function RecoCard({
  rec,
  out,
  template,
  node,
  hypothesis,
  expected,
  canLaunch,
}: {
  rec: Recommendation;
  out: RecommendOut;
  template: RunTemplate | undefined;
  node: string;
  hypothesis: string;
  expected: string;
  canLaunch: boolean;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useState<Record<string, ParamValue>>({});
  useEffect(() => setParams(defaults(template?.params ?? [], rec.params)), [template, rec.params]);
  const go = useMutation({
    mutationFn: () =>
      launchAnalysis({
        snapshot_id: out.snapshot.id,
        template: rec.template,
        params,
        node,
        hypothesis,
        expected,
        choice: {
          key: rec.key,
          title: rec.title,
          why: rec.why,
          primary: rec.primary,
          net: rec.net,
          as_authors: rec.as_authors,
          evidence: rec.evidence,
          article: rec.as_authors ? (out.authors?.article_title ?? "") : "",
          task: out.task.key,
        },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      void qc.invalidateQueries({ queryKey: ["hypotheses"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/run/${r.run_id}`);
    },
  });
  const badge = rec.as_authors ? (
    <span className="badge st-done">Как у авторов</span>
  ) : rec.primary ? (
    <span className="badge st-done">Рекомендуем</span>
  ) : (
    <span className="badge st-planned">Альтернатива</span>
  );
  return (
    <article className={rec.primary ? "card reco reco-primary" : "card reco"} aria-label={rec.title}>
      <div className="kb-meta">
        {badge}
        {rec.method_title && <span className="muted">{rec.method_title}</span>}
      </div>
      <h3 className="h3">{rec.title}</h3>
      <ul className="list">
        {rec.why.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
      {rec.warnings.map((w) => (
        <p key={w} className="blockers">
          {w}
        </p>
      ))}
      {template && rec.runnable && (
        <details>
          <summary>Параметры расчёта (уже заполнены — можно поправить)</summary>
          <ParamsEditor params={template.params} snapshotId={out.snapshot.id} value={params} onChange={setParams} idPrefix={`reco-${rec.key}`} />
        </details>
      )}
      {template && rec.runnable && (
        <RunCost template={rec.template} snapshotId={out.snapshot.id} params={params} onApply={(p) => setParams({ ...params, ...p })} />
      )}
      {go.isError && (
        <p className="error" role="alert">
          {go.error.message}
        </p>
      )}
      {canLaunch && rec.runnable && (
        <div>
          <button type="button" className={rec.primary ? "btn-primary" : "btn-ghost"} disabled={go.isPending} onClick={() => go.mutate()}>
            {go.isPending ? "Ставлю расчёт…" : "Запустить расчёт"}
          </button>
        </div>
      )}
    </article>
  );
}

/** Классификация «тип задачи → сети»: что платформа рекомендует и что умеет считать. */
function CatalogTable() {
  const c = useQuery({ queryKey: ["analysis-catalog"], queryFn: getCatalog, staleTime: Infinity });
  if (!Array.isArray(c.data?.tasks) || !Array.isArray(c.data?.nets)) return null;
  const nets = new Map(c.data.nets.map((n) => [n.key, n]));
  return (
    <details className="card details-card">
      <summary>Как платформа подбирает сеть: тип задачи → сети</summary>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Тип задачи</th>
              <th scope="col">Пример</th>
              <th scope="col">Сети и методы — по порядку рекомендации</th>
            </tr>
          </thead>
          <tbody>
            {c.data.tasks.map((t) => (
              <tr key={t.key}>
                <td>{t.title}</td>
                <td className="muted">{t.example}</td>
                <td>
                  {t.nets.map((k, i) => {
                    const n = nets.get(k);
                    return (
                      <span key={k}>
                        {i > 0 && " → "}
                        {n?.title ?? k}
                        {n && !n.runnable && <span className="muted"> (в библиотеке пока нет)</span>}
                      </span>
                    );
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function Analysis() {
  const me = useMe();
  const canLaunch = canRun(me.data?.role);
  const [search] = useSearchParams();
  const hypothesis = search.get("h") ?? "";
  const templates = useQuery({ queryKey: ["run-templates"], queryFn: listTemplates });
  const hyps = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses, enabled: hypothesis !== "" });
  const idea = (Array.isArray(hyps.data) ? hyps.data : []).find((h) => h.code === hypothesis);
  // версии данных-таблицы: их видят общие методы библиотеки
  const snapshots = useMemo(() => {
    const seen = new Map<number, RunTemplate["snapshots"][number]>();
    for (const t of templates.data ?? []) if (t.scope === "generic") for (const s of t.snapshots) seen.set(s.id, s);
    return [...seen.values()];
  }, [templates.data]);
  const [node, setNode] = useState("");
  // из «Поиска связей»: ?snapshot=…&target=… — та же версия данных и показатель найденной связи
  const fromSnapshot = Number(search.get("snapshot")) || "";
  const [snapshot, setSnapshot] = useState<number | "">(fromSnapshot);
  const [sheet, setSheet] = useState("");
  const [target, setTarget] = useState(search.get("target") ?? "");
  // лист и показатель сбрасываются, только когда версия данных сменилась (не при первом показе
  // и не при повторном вызове эффекта в StrictMode) — показатель из адреса сохраняется
  const shownSnapshot = useRef(snapshot);
  useEffect(() => {
    if (shownSnapshot.current === snapshot) return;
    shownSnapshot.current = snapshot;
    setSheet("");
    setTarget("");
  }, [snapshot]);
  // идея предлагает набор данных — подставляем его последнюю версию
  const suggested = idea?.suggested.dataset;
  useEffect(() => {
    if (snapshot !== "" || !suggested) return;
    const first = snapshots.find((s) => s.dataset === suggested);
    if (first) setSnapshot(first.id);
  }, [suggested, snapshots, snapshot]);
  const q = useQuery({
    queryKey: ["analysis", snapshot, sheet, target, node, hypothesis],
    queryFn: () => recommend({ snapshot_id: snapshot as number, sheet, target, node, hypothesis }),
    enabled: snapshot !== "",
    retry: false,
  });
  const r = q.data;
  // пункт методики идеи — сразу в поле, чтобы было видно, к чему относится анализ; один раз —
  // дальше человек может его сменить или очистить
  const ideaNode = r?.hypothesis?.node ?? "";
  const nodeSet = useRef(false);
  useEffect(() => {
    if (ideaNode && !nodeSet.current) {
      nodeSet.current = true;
      setNode((n) => n || ideaNode);
    }
  }, [ideaNode]);
  // идея уже проверяется — следующий расчёт (замена сети) добавится в ту же проверку
  const testing = idea?.status === "testing" && Boolean(idea.experiment);
  const launchable = !hypothesis || idea?.status === "accepted" || testing;
  // по новой идее критерий записывается до расчёта — как в мастере проверки
  const [expected, setExpected] = useState("");
  const needCriterion = Boolean(hypothesis) && idea?.status === "accepted";
  const criterionOk = !needCriterion || expected.trim().length >= 3;
  const candidates = new Set((r?.target_candidates ?? []).map((c) => c.column));
  const byKey = (key: string) => (templates.data ?? []).find((t) => t.key === key);

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">АНАЛИЗ ДАННЫХ</span>
        <h1 className="page-title">Анализ данных</h1>
        <p className="lead">
          Выберите, что изучаете, и набор данных — платформа подберёт метод или нейросеть, объяснит выбор и запустит
          расчёт. Расчёт попадёт в «Проверки» со всем, что нужно, чтобы его повторить.
        </p>
      </section>

      {hypothesis && (
        <section className="card" aria-label="Идея для проверки">
          <span className="eyebrow">ИДЕЯ ДЛЯ ПРОВЕРКИ · {hypothesis}</span>
          <h2 className="h2">{idea?.title ?? r?.hypothesis?.title ?? "Загрузка…"}</h2>
          {(idea?.statement ?? r?.hypothesis?.statement) && <p>{idea?.statement ?? r?.hypothesis?.statement}</p>}
          {idea && !launchable && (
            <p className="blockers">Идея ещё не принята к проверке: рекомендации видны, но запустить расчёт по ней нельзя.</p>
          )}
          {testing && idea && (
            <p className="muted">
              Идея уже проверяется в <Link to={`/experiments/${idea.experiment}`} className="mono">{idea.experiment}</Link>: новый
              расчёт — например, с заменой сети — добавится в эту же проверку.
            </p>
          )}
          {r?.authors ? (
            <NextStep>
              В статье «{r.authors.article_title}» авторы пользуются: <strong>{r.authors.title}</strong>
              {!r.authors.runnable && r.authors.nearest_title && ` — в библиотеке её пока нет, ближайшая замена: ${r.authors.nearest_title}`}.{" "}
              {r.task.key === "predict"
                ? "Первой стоит карточка «Как у авторов», ниже — замены."
                : r.authors_note || "Выберите показатель, который предсказываем, — тогда появится карточка «Как у авторов»."}
            </NextStep>
          ) : (
            r?.authors_note && <p className="muted">{r.authors_note}</p>
          )}
        </section>
      )}

      <section className="card wizard" aria-labelledby="an-1">
        <h2 className="h2" id="an-1">
          1. Что изучаем
        </h2>
        <div className="form-grid">
          <label className="field" htmlFor="an-node">
            Пункт методики (необязательно)
            <NodeSelect id="an-node" value={node} onChange={setNode} />
          </label>
          <label className="field" htmlFor="an-snap">
            Набор данных и версия
            <select id="an-snap" value={snapshot} onChange={(e) => setSnapshot(e.target.value ? Number(e.target.value) : "")}>
              <option value="">— выберите —</option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.dataset} · {s.version}
                  {s.row_count ? ` · ${s.row_count} строк` : ""}
                </option>
              ))}
            </select>
          </label>
          {r && r.sheets.length > 1 && (
            <label className="field span-2" htmlFor="an-sheet">
              Лист книги
              <select id="an-sheet" value={sheet || r.sheet} onChange={(e) => setSheet(e.target.value)}>
                {r.sheets.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {templates.isSuccess && snapshots.length === 0 && (
          <p className="muted">
            Версий данных-таблиц пока нет — загрузите файл в разделе <Link to="/data">«Данные»</Link>.
          </p>
        )}
      </section>

      {snapshot !== "" && (
        <section className="card wizard" aria-labelledby="an-2">
          <h2 className="h2" id="an-2">
            2. Показатель
          </h2>
          <label className="field" htmlFor="an-target">
            Что предсказываем (результат R)
            <select id="an-target" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">— не выбран: сравнить показатели между собой —</option>
              {(r?.target_candidates ?? []).length > 0 && (
                <optgroup label="Подходят к пункту методики">
                  {(r?.target_candidates ?? []).map((c) => (
                    <option key={`c-${c.column}`} value={c.column}>
                      {c.column}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Все числовые столбцы">
                {(r?.numeric ?? []).filter((c) => !candidates.has(c)).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
          {r && r.target_candidates.length > 0 && !target && (
            <p className="muted">
              Подсказка: «{r.target_candidates[0]?.column}» — {r.target_candidates[0]?.reason}.
            </p>
          )}
          {q.isPending && <p className="muted">Смотрю на данные…</p>}
          {q.isError && (
            <p className="error" role="alert">
              {q.error.message}
            </p>
          )}
        </section>
      )}

      {r && (
        <section className="wizard" aria-labelledby="an-3">
          <h2 className="h2" id="an-3">
            3. Рекомендация
          </h2>
          <NextStep>
            <strong>{r.task.title}.</strong> {r.task.text}
            {r.rows !== null && ` В версии данных ${r.rows} строк, числовых столбцов ${r.numeric.length}.`}
          </NextStep>
          {!canLaunch && <p className="muted">Запускать расчёты могут исследователи — рекомендации видны всем.</p>}
          {canLaunch && needCriterion && (
            <label className="field" htmlFor="an-expected">
              Что подтвердит или опровергнет идею (записывается до расчёта)
              <textarea
                id="an-expected"
                rows={2}
                value={expected}
                onChange={(e) => setExpected(e.target.value)}
                placeholder="Например: подтвердится, если R² модели выше, чем на перемешанной цели, в 80 % разбиений"
              />
              {!criterionOk && <span className="muted">Без критерия расчёт по идее не запустить.</span>}
            </label>
          )}
          <div className="reco-list">
            {r.recommendations.map((rec) => (
              <RecoCard
                key={rec.key}
                rec={rec}
                out={r}
                template={byKey(rec.template)}
                node={node}
                hypothesis={launchable ? hypothesis : ""}
                expected={needCriterion ? expected : ""}
                canLaunch={canLaunch && launchable && criterionOk}
              />
            ))}
          </div>
        </section>
      )}

      <CatalogTable />
    </>
  );
}
