import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { launchAnalysis, recommend, type Recommendation } from "../api/analysis";
import { useMe } from "../auth/useAuth";
import { NodeSelect } from "../components/NodeSelect";
import { defaults, ParamsEditor, type ParamValue } from "../components/ParamsEditor";
import { canRun, NextStep } from "../components/Ux";
import { listTemplates, type RunTemplate } from "./RunPage";

/** Карточка рекомендации: метод, почему, параметры, запуск. */
function RecoCard({
  rec,
  template,
  snapshotId,
  node,
  canLaunch,
}: {
  rec: Recommendation;
  template: RunTemplate | undefined;
  snapshotId: number;
  node: string;
  canLaunch: boolean;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useState<Record<string, ParamValue>>({});
  useEffect(() => setParams(defaults(template?.params ?? [], rec.params)), [template, rec.params]);
  const go = useMutation({
    mutationFn: () =>
      launchAnalysis({
        snapshot_id: snapshotId,
        template: rec.template,
        params,
        node,
        choice: { key: rec.key, title: rec.title, why: rec.why, primary: rec.primary, net: rec.net },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/run/${r.run_id}`);
    },
  });
  return (
    <article className={rec.primary ? "card reco reco-primary" : "card reco"} aria-label={rec.title}>
      <div className="kb-meta">
        {rec.primary ? <span className="badge st-done">Рекомендуем</span> : <span className="badge st-planned">Альтернатива</span>}
        <span className="muted">{rec.method_title}</span>
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
          <ParamsEditor params={template.params} snapshotId={snapshotId} value={params} onChange={setParams} idPrefix={`reco-${rec.key}`} />
        </details>
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

export function Analysis() {
  const me = useMe();
  const canLaunch = canRun(me.data?.role);
  const templates = useQuery({ queryKey: ["run-templates"], queryFn: listTemplates });
  // версии данных-таблицы: их видят общие методы библиотеки
  const snapshots = useMemo(() => {
    const seen = new Map<number, RunTemplate["snapshots"][number]>();
    for (const t of templates.data ?? []) if (t.scope === "generic") for (const s of t.snapshots) seen.set(s.id, s);
    return [...seen.values()];
  }, [templates.data]);
  const [node, setNode] = useState("");
  const [snapshot, setSnapshot] = useState<number | "">("");
  const [sheet, setSheet] = useState("");
  const [target, setTarget] = useState("");
  useEffect(() => {
    setSheet("");
    setTarget("");
  }, [snapshot]);
  const q = useQuery({
    queryKey: ["analysis", snapshot, sheet, target, node],
    queryFn: () => recommend({ snapshot_id: snapshot as number, sheet, target, node }),
    enabled: snapshot !== "",
    retry: false,
  });
  const r = q.data;
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
          <div className="reco-list">
            {r.recommendations.map((rec) => (
              <RecoCard key={rec.key} rec={rec} template={byKey(rec.template)} snapshotId={r.snapshot.id} node={node} canLaunch={canLaunch} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
