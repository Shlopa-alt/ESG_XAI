import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { experimentFromHypothesis, type Hypothesis, listHypotheses } from "../api/hypotheses";
import { launch, listTemplates, type RunTemplate } from "../pages/RunPage";
import { defaults, ParamsEditor, type ParamValue } from "./ParamsEditor";
import { type Proposal, proposalsFor } from "./ProposalPanel";
import { NextStep, Stepper } from "./Ux";

type Mode = "model" | "manual";

async function postProposal<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api/experiment-proposals${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || data === null) throw new Error(typeof data?.detail === "string" ? data.detail : `Ошибка ${res.status}`);
  return data;
}

/** Шаг 1: какую гипотезу проверяем. */
function PickHypothesis({
  list,
  value,
  onChange,
}: {
  list: Hypothesis[];
  value: string;
  onChange: (code: string) => void;
}) {
  if (list.length === 0) {
    return (
      <div className="wizard-empty">
        <p>Нет гипотез, принятых к проверке.</p>
        <p className="muted">
          Гипотезу сначала предлагают (человек или Qwen), затем рецензент принимает её — после этого она появится здесь.
        </p>
        <Link to="/hypotheses" className="btn-ghost">
          Перейти к гипотезам
        </Link>
      </div>
    );
  }
  return (
    <fieldset className="choice-list">
      <legend className="sr-only">Гипотеза для проверки</legend>
      {list.map((h) => (
        <label key={h.code} className={value === h.code ? "choice active" : "choice"} aria-label={`${h.code} ${h.title}`}>
          <input type="radio" name="wizard-h" value={h.code} checked={value === h.code} onChange={() => onChange(h.code)} />
          <span className="choice-body">
            <span className="choice-title">
              <span className="mono">{h.code}</span> {h.title}
              {h.source === "qwen" && <span className="badge st-running">от Qwen</span>}
            </span>
            <span className="muted">{h.statement}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** Предложение Qwen в коротком виде — что именно будет посчитано. */
function ProposalSummary({ p }: { p: Proposal }) {
  const params = Object.entries(p.params);
  return (
    <div className="proposal-summary">
      <dl className="dl">
        <dt>Эксперимент</dt>
        <dd>{p.title}</dd>
        <dt>Метод</dt>
        <dd>{p.method_title || <span className="error">не выбран</span>}</dd>
        <dt>Данные</dt>
        <dd className="mono">{p.snapshot || <span className="error">не выбраны</span>}</dd>
        {params.length > 0 && (
          <>
            <dt>Параметры</dt>
            <dd className="mono">
              {params.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ")}
            </dd>
          </>
        )}
        {p.expected && (
          <>
            <dt>Критерий</dt>
            <dd>{p.expected}</dd>
          </>
        )}
      </dl>
      {p.setup.length > 0 && (
        <details>
          <summary>Протокол — {p.setup.length} шаг(ов)</summary>
          <ol className="list">
            {p.setup.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
        </details>
      )}
      {p.rationale && (
        <details>
          <summary>Почему модель выбрала так</summary>
          <p className="muted pre-line">{p.rationale}</p>
        </details>
      )}
    </div>
  );
}

/**
 * Мастер «гипотеза → как проверить → запуск».
 * Режим «модель решит» — предложение Qwen одобряется как есть; «задам сам» — метод, срез и параметры
 * выбирает человек (если предложение Qwen есть, оно служит заготовкой и одобряется с правками).
 */
export function ExperimentWizard({ initialHypothesis = "" }: { initialHypothesis?: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const hyps = useQuery({ queryKey: ["hypotheses"], queryFn: listHypotheses });
  const templates = useQuery({ queryKey: ["run-templates"], queryFn: listTemplates });
  const accepted = useMemo(() => (Array.isArray(hyps.data) ? hyps.data.filter((h) => h.status === "accepted") : []), [hyps.data]);
  const [code, setCode] = useState(initialHypothesis);
  const [mode, setMode] = useState<Mode>("model");
  const h = accepted.find((x) => x.code === code);

  // выбранной гипотезы нет среди принятых (или не выбрана) — берём первую
  useEffect(() => {
    const first = accepted[0];
    if (first && !accepted.some((x) => x.code === code)) setCode(first.code);
  }, [accepted, code]);

  const proposals = useQuery({
    queryKey: ["proposals", code],
    queryFn: () => proposalsFor(code),
    enabled: Boolean(h),
    refetchInterval: (q) => ((q.state.data ?? []).some((p) => p.status === "proposed") ? false : 20_000),
  });
  const open = (proposals.data ?? []).find((p) => p.status === "proposed");

  // ручной режим: заготовка из предложения Qwen, если оно есть
  const [method, setMethod] = useState("");
  const [snapshot, setSnapshot] = useState<number | "">("");
  const [params, setParams] = useState<Record<string, ParamValue>>({});
  const [protocol, setProtocol] = useState("");
  const [expected, setExpected] = useState("");
  const all = templates.data ?? [];
  // без предложения Qwen эксперимент создаётся заново — повторы чужих экспериментов тут не подходят
  const methods: RunTemplate[] = open ? all : all.filter((t) => t.scope === "generic");
  const t = methods.find((x) => x.key === method);
  useEffect(() => {
    setMethod(open?.method || "");
    setSnapshot(open?.snapshot_id ?? "");
    setProtocol(open?.setup.join("\n") ?? "");
    setExpected(open?.expected ?? "");
  }, [open?.id, open?.method, open?.snapshot_id, open?.setup, open?.expected, code]);
  useEffect(() => {
    setParams(defaults(t?.params ?? [], open && method === open.method ? open.params : {}));
    if (t && snapshot !== "" && !t.snapshots.some((s) => s.id === snapshot)) setSnapshot(t.snapshots[0]?.id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- сбрасываем параметры только при смене метода
  }, [t, open?.id]);

  const done = (runId: number | null, exp: string) => {
    void qc.invalidateQueries({ queryKey: ["hypotheses"] });
    void qc.invalidateQueries({ queryKey: ["experiments"] });
    void qc.invalidateQueries({ queryKey: ["runs"] });
    void qc.invalidateQueries({ queryKey: ["proposals", code] });
    navigate(runId ? `/run/${runId}` : `/experiments/${exp}`);
  };

  const go = useMutation({
    mutationFn: async () => {
      const setup = protocol.split("\n").map((x) => x.trim()).filter(Boolean);
      if (mode === "model") {
        if (!open) throw new Error("Предложения модели ещё нет");
        const r = await postProposal<Proposal>(`/${open.id}/approve`, {});
        return { run: r.run_id, exp: r.experiment };
      }
      if (!t || snapshot === "") throw new Error("Выберите метод и данные");
      if (open) {
        const r = await postProposal<Proposal>(`/${open.id}/approve`, {
          method: t.key,
          snapshot_id: snapshot,
          params,
          setup,
          expected,
        });
        return { run: r.run_id, exp: r.experiment };
      }
      // предложения нет — эксперимент из гипотезы и запуск выбранного метода
      const hyp = await experimentFromHypothesis(code);
      const run = await launch({ template: t.key, snapshot_id: snapshot, params, experiment: hyp.experiment });
      return { run: run.id, exp: hyp.experiment };
    },
    onSuccess: (r) => done(r.run, r.exp),
  });

  const ready = mode === "model" ? Boolean(open && !open.problems) : Boolean(t && snapshot !== "");
  const step = !h ? 0 : mode === "model" && !open ? 1 : 2;

  return (
    <section className="card wizard" aria-labelledby="wizard-title">
      <h2 className="h2" id="wizard-title">
        Проверить гипотезу экспериментом
      </h2>
      <Stepper steps={["Гипотеза", "Как проверить", "Запуск"]} current={step} label="Шаги запуска" />

      <div className="wizard-step">
        <h3 className="h3">1. Какую гипотезу проверяем</h3>
        {hyps.isPending ? <p className="muted">Загрузка…</p> : <PickHypothesis list={accepted} value={code} onChange={setCode} />}
      </div>

      {h && (
        <div className="wizard-step">
          <h3 className="h3">2. Как построить эксперимент</h3>
          <div className="mode-switch" role="radiogroup" aria-label="Кто выбирает метод и данные">
            <label className={mode === "model" ? "mode active" : "mode"} aria-label="Пусть решит модель">
              <input type="radio" name="wizard-mode" checked={mode === "model"} onChange={() => setMode("model")} />
              <span>
                <strong>Пусть решит модель</strong>
                <span className="muted">Qwen сама подберёт метод из библиотеки, срез данных и параметры по гипотезе и её опорам.</span>
              </span>
            </label>
            <label className={mode === "manual" ? "mode active" : "mode"} aria-label="Задам сам">
              <input type="radio" name="wizard-mode" checked={mode === "manual"} onChange={() => setMode("manual")} />
              <span>
                <strong>Задам сам</strong>
                <span className="muted">
                  Вы выбираете метод, данные и параметры{open ? " — предложение Qwen подставлено как заготовка" : ""}.
                </span>
              </span>
            </label>
          </div>

          {mode === "model" &&
            (open ? (
              <>
                <ProposalSummary p={open} />
                {open.problems && (
                  <p className="blockers" role="status">
                    Модель ошиблась: {open.problems}. Переключитесь на «Задам сам» и поправьте.
                  </p>
                )}
              </>
            ) : proposals.isPending ? (
              <p className="muted">Загрузка…</p>
            ) : (
              <div className="waiting" role="status">
                <span className="spinner" aria-hidden="true" />
                <span>
                  Qwen готовит предложение эксперимента — обычно несколько минут, страница обновится сама. Не хотите ждать —
                  выберите «Задам сам».
                </span>
              </div>
            ))}

          {mode === "manual" && (
            <div className="manual">
              <div className="form-grid">
                <label className="field">
                  Метод
                  <select value={method} onChange={(e) => setMethod(e.target.value)}>
                    <option value="">— выберите метод —</option>
                    {methods.map((x) => (
                      <option key={x.key} value={x.key}>
                        {x.scope === "replication" ? "Повтор · " : ""}
                        {x.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Данные (срез датасета)
                  <select value={snapshot} onChange={(e) => setSnapshot(e.target.value ? Number(e.target.value) : "")} disabled={!t}>
                    <option value="">{t ? "— выберите срез —" : "сначала выберите метод"}</option>
                    {(t?.snapshots ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.dataset} · {s.version}
                        {s.row_count ? ` · ${s.row_count} строк` : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {t && <p className="muted">{t.description}</p>}
              {t && t.snapshots.length === 0 && (
                <p className="blockers">
                  Для этого метода нет подходящих срезов — загрузите данные на странице датасета в{" "}
                  <Link to="/knowledge">базе знаний</Link>.
                </p>
              )}
              {t && (
                <ParamsEditor
                  params={t.params}
                  snapshotId={snapshot === "" ? null : snapshot}
                  value={params}
                  onChange={setParams}
                  idPrefix="wizard"
                />
              )}
              {open && (
                <details>
                  <summary>Протокол и критерий (необязательно)</summary>
                  <label className="field">
                    Протокол — шаг на строку
                    <textarea rows={4} value={protocol} onChange={(e) => setProtocol(e.target.value)} />
                  </label>
                  <label className="field">
                    Что подтвердит или опровергнет гипотезу
                    <textarea rows={2} value={expected} onChange={(e) => setExpected(e.target.value)} />
                  </label>
                </details>
              )}
            </div>
          )}
        </div>
      )}

      {h && (
        <div className="wizard-step">
          <h3 className="h3">3. Запуск</h3>
          <NextStep>
            Будет создан эксперимент по гипотезе <span className="mono">{h.code}</span> и поставлен расчёт на сервер лаборатории.
            Вы попадёте на страницу запуска с ходом расчёта; по готовности Qwen напишет отчёт на странице эксперимента.
          </NextStep>
          {go.isError && (
            <p className="error" role="alert">
              {go.error.message}
            </p>
          )}
          <div>
            <button type="button" className="btn-primary" disabled={!ready || go.isPending} onClick={() => go.mutate()}>
              {go.isPending ? "Создаю и запускаю…" : "Создать эксперимент и запустить"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
