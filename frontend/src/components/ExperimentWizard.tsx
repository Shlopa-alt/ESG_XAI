import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { experimentFromHypothesis, type Hypothesis, listHypotheses } from "../api/hypotheses";
import { listTemplates, type RunTemplate } from "../pages/RunPage";
import { defaults, ParamsEditor, type ParamValue } from "./ParamsEditor";
import {
  approveProposal,
  manualProposal,
  type Proposal,
  type ProposalWait,
  proposalsFor,
  proposalWait,
  rejectProposal,
  requestProposal,
} from "./ProposalPanel";
import { NextStep, Stepper } from "./Ux";

type Mode = "model" | "manual";

const POLL_MS = 20_000;

const isEmpty = (v: ParamValue | undefined) => v === undefined || v === "" || (Array.isArray(v) && v.length === 0);

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
          <summary>Протокол — шагов: {p.setup.length}</summary>
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

/** Предложения нет: честно показываем почему — ждать нечего, если задача сорвалась или её не было. */
function ProposalMissing({
  wait,
  rejected,
  retrying,
  onRetry,
}: {
  wait: ProposalWait;
  rejected: Proposal | undefined;
  retrying: boolean;
  onRetry: () => void;
}) {
  if (wait.job === "queued" || wait.job === "running") {
    return (
      <div className="waiting" role="status">
        <span className="spinner" aria-hidden="true" />
        <span>
          {wait.job === "running"
            ? "Qwen готовит предложение эксперимента."
            : "Задача стоит в очереди Qwen. Очередь идёт по порядку: если модель занята, например, графом, ждать можно долго."}{" "}
          {!wait.worker && "Обработчик Qwen сейчас не на связи: работа продолжится, когда он вернётся. "}
          Страница обновится сама. Не хотите ждать — выберите «Задам сам».
        </span>
      </div>
    );
  }
  return (
    <div className="proposal-missing" role="status">
      <p>
        {rejected
          ? `Предложение Qwen «${rejected.title}» отклонено (${rejected.decided_by}): ${rejected.note}.`
          : wait.job === "failed"
            ? "Qwen не смогла подготовить предложение. Подробности — у владельца на странице «Задачи Qwen»."
            : "Предложения нет: Qwen его не готовит."}{" "}
        Попросите модель ещё раз или выберите «Задам сам».
      </p>
      <button type="button" className="btn-ghost" disabled={retrying} onClick={onRetry}>
        {retrying ? "Ставлю в очередь…" : "Попросить Qwen ещё раз"}
      </button>
    </div>
  );
}

/**
 * Мастер «гипотеза → как проверить → запуск».
 * «Взять предложение Qwen» — человек одобряет то, что подобрала модель, или отклоняет с объяснением;
 * «Задам сам» — метод, срез и параметры выбирает человек (предложение Qwen, если есть, — заготовка).
 * Эксперимент с расчётом создаётся на сервере одним действием: не поставился расчёт — нет и эксперимента.
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
    refetchInterval: (q) => ((q.state.data ?? []).some((p) => p.status === "proposed") ? false : POLL_MS),
  });
  const open = (proposals.data ?? []).find((p) => p.status === "proposed");
  const lastRejected = (proposals.data ?? []).find((p) => p.status === "rejected");
  const wait = useQuery({
    queryKey: ["proposal-wait", code],
    queryFn: () => proposalWait(code),
    enabled: Boolean(h) && !open,
    refetchInterval: POLL_MS,
  });

  // ручной режим: заготовка из предложения Qwen, если оно есть
  const [title, setTitle] = useState("");
  const [method, setMethod] = useState("");
  const [snapshot, setSnapshot] = useState<number | "">("");
  const [params, setParams] = useState<Record<string, ParamValue>>({});
  const [protocol, setProtocol] = useState("");
  const [expected, setExpected] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const all = templates.data ?? [];
  // без предложения Qwen эксперимент создаётся заново — повторы чужих экспериментов тут не подходят
  const methods: RunTemplate[] = open ? all : all.filter((t) => t.scope === "generic");
  const t = methods.find((x) => x.key === method);
  useEffect(() => {
    setTitle(open?.title || h?.title || "");
    setMethod(open?.method || "");
    setSnapshot(open?.snapshot_id ?? "");
    setProtocol(open?.setup.join("\n") ?? "");
    setExpected(open?.expected ?? "");
  }, [open?.id, open?.title, open?.method, open?.snapshot_id, open?.setup, open?.expected, h?.title, code]);
  useEffect(() => {
    setParams(defaults(t?.params ?? [], open && method === open.method ? open.params : {}));
    if (t && snapshot !== "" && !t.snapshots.some((s) => s.id === snapshot)) setSnapshot(t.snapshots[0]?.id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- сбрасываем параметры только при смене метода
  }, [t, open?.id]);

  // что будет посчитано: повтор расчёта как есть редко проверяет новую гипотезу — человек подтверждает явно
  const chosen = mode === "model" ? all.find((x) => x.key === open?.method) : t;
  const replication = chosen?.scope === "replication";
  useEffect(() => setConfirmed(false), [chosen?.key, code]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["proposals", code] });
    void qc.invalidateQueries({ queryKey: ["proposal-wait", code] });
  };
  const done = (runId: number | null, exp: string) => {
    refresh();
    void qc.invalidateQueries({ queryKey: ["hypotheses"] });
    void qc.invalidateQueries({ queryKey: ["experiments"] });
    void qc.invalidateQueries({ queryKey: ["runs"] });
    navigate(runId ? `/run/${runId}` : `/experiments/${exp}`);
  };

  const go = useMutation({
    mutationFn: () => {
      if (mode === "model") {
        if (!open) throw new Error("Предложения модели ещё нет");
        return approveProposal(open.id, { confirm_replication: confirmed });
      }
      if (!t || snapshot === "") throw new Error("Выберите метод и данные");
      const setup = protocol.split("\n").map((x) => x.trim()).filter(Boolean);
      const common = { title: title.trim(), params, setup, expected };
      return open
        ? approveProposal(open.id, { ...common, method: t.key, snapshot_id: snapshot, confirm_replication: confirmed })
        : manualProposal({ ...common, hypothesis: code, template: t.key, snapshot_id: snapshot });
    },
    onSuccess: (r) => done(r.run_id, r.experiment),
  });
  // карточка без расчёта: подходящего метода или данных пока нет, а проверку уже начали готовить
  const cardOnly = useMutation({
    mutationFn: () => experimentFromHypothesis(code),
    onSuccess: (r) => done(null, r.experiment),
  });
  const reject = useMutation({
    mutationFn: () => {
      if (!open) throw new Error("Предложения модели ещё нет");
      return rejectProposal(open.id, note.trim());
    },
    onSuccess: () => {
      setNote("");
      refresh();
    },
  });
  const retry = useMutation({ mutationFn: () => requestProposal(code), onSuccess: refresh });
  const busy = go.isPending || cardOnly.isPending || reject.isPending;
  const error = go.error ?? cardOnly.error ?? reject.error ?? retry.error;

  // чего не хватает — кнопка неактивна, и человек видит почему
  const missing: string[] =
    mode === "model"
      ? []
      : [
          ...(t ? [] : ["метод"]),
          ...(snapshot === "" ? ["данные"] : []),
          ...(t?.params ?? [])
            .filter((p) => p.required && p.kind !== "int" && isEmpty(params[p.name]))
            .map((p) => p.label.toLowerCase()),
          ...(expected.trim().length < 3 ? ["что подтвердит или опровергнет гипотезу"] : []),
        ];
  if (replication && !confirmed) missing.push("подтверждение, что повтор проверяет эту гипотезу");
  const ready = mode === "model" ? Boolean(open && !open.problems) && missing.length === 0 : missing.length === 0;
  const step = !h ? 0 : mode === "model" && !open ? 1 : 2;

  return (
    <section className="card wizard" aria-labelledby="wizard-title">
      <h2 className="h2" id="wizard-title">
        Проверить гипотезу экспериментом
      </h2>
      <Stepper steps={["Гипотеза", "Как проверить", "Запуск"]} current={step} label="Шаги запуска" />

      <div className="wizard-step">
        <h3 className="h3">1. Какую гипотезу проверяем</h3>
        {hyps.isPending ? (
          <p className="muted">Загрузка…</p>
        ) : hyps.isError ? (
          <p className="error" role="alert">
            Не удалось загрузить гипотезы: {hyps.error.message}
          </p>
        ) : (
          <PickHypothesis list={accepted} value={code} onChange={setCode} />
        )}
      </div>

      {h && (
        <div className="wizard-step">
          <h3 className="h3">2. Как построить эксперимент</h3>
          <div className="mode-switch" role="radiogroup" aria-label="Кто выбирает метод и данные">
            <label className={mode === "model" ? "mode active" : "mode"} aria-label="Взять предложение Qwen">
              <input type="radio" name="wizard-mode" checked={mode === "model"} onChange={() => setMode("model")} />
              <span>
                <strong>Взять предложение Qwen</strong>
                <span className="muted">Модель подбирает метод, срез и параметры по гипотезе и её опорам. Решение за вами: проверьте и одобрите или отклоните.</span>
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
            (proposals.isError ? (
              <p className="error" role="alert">
                Не удалось загрузить предложение: {proposals.error.message}
              </p>
            ) : open ? (
              <>
                <ProposalSummary p={open} />
                {open.problems && (
                  <p className="blockers" role="status">
                    Модель ошиблась: {open.problems}. Переключитесь на «Задам сам» и поправьте или отклоните предложение.
                  </p>
                )}
                <details className="proposal-reject">
                  <summary>Отклонить предложение</summary>
                  <div className="review-form">
                    <label className="field inline grow">
                      Почему отклоняете (увидит лаборатория)
                      <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
                    </label>
                    <button type="button" className="btn-ghost" disabled={busy || note.trim().length < 3} onClick={() => reject.mutate()}>
                      Отклонить
                    </button>
                  </div>
                </details>
              </>
            ) : wait.isError ? (
              <p className="error" role="alert">
                Не удалось узнать, что с предложением: {wait.error.message}
              </p>
            ) : proposals.isPending || wait.isPending ? (
              <p className="muted">Загрузка…</p>
            ) : (
              <ProposalMissing wait={wait.data} rejected={lastRejected} retrying={retry.isPending} onRetry={() => retry.mutate()} />
            ))}

          {mode === "manual" && (
            <div className="manual">
              {templates.isError && (
                <p className="error" role="alert">
                  Не удалось загрузить библиотеку методов: {templates.error.message}
                </p>
              )}
              <label className="field">
                Название эксперимента
                <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={512} />
              </label>
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
              <label className="field">
                Что подтвердит или опровергнет гипотезу (записывается до расчёта)
                <textarea rows={2} value={expected} onChange={(e) => setExpected(e.target.value)} />
              </label>
              <label className="field">
                Протокол — шаг на строку (необязательно)
                <textarea rows={4} value={protocol} onChange={(e) => setProtocol(e.target.value)} />
              </label>
            </div>
          )}
        </div>
      )}

      {h && (
        <div className="wizard-step">
          <h3 className="h3">3. Запуск</h3>
          <NextStep>
            Будет создан эксперимент по гипотезе <span className="mono">{h.code}</span> и поставлен расчёт на сервер лаборатории
            {chosen ? ` (лимит — ${chosen.limit_min} мин)` : ""}. Вы попадёте на страницу запуска с ходом расчёта; по готовности
            Qwen напишет отчёт на странице эксперимента.
          </NextStep>
          {replication && chosen && (
            <div className="blockers" role="status">
              <p>
                «{chosen.title}» — повтор опубликованного расчёта как есть: {chosen.description} Новых показателей он не считает,
                поэтому гипотезу о другом результате или других данных он не проверит.
              </p>
              <label className="check">
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                Понимаю: этот повтор действительно проверяет гипотезу {h.code}
              </label>
            </div>
          )}
          {error && (
            <p className="error" role="alert">
              {error.message}
            </p>
          )}
          {mode === "manual" && missing.length > 0 && <p className="muted">Чтобы запустить, укажите: {missing.join(", ")}.</p>}
          <div className="review-form">
            <button type="button" className="btn-primary" disabled={!ready || busy} onClick={() => go.mutate()}>
              {go.isPending ? "Создаю и запускаю…" : mode === "model" ? "Одобрить предложение и запустить" : "Создать эксперимент и запустить"}
            </button>
            {mode === "manual" && (
              <button type="button" className="btn-ghost" disabled={busy} onClick={() => cardOnly.mutate()}>
                {cardOnly.isPending ? "Создаю…" : "Создать только карточку, без расчёта"}
              </button>
            )}
          </div>
          {mode === "manual" && (
            <p className="muted">
              Карточка без расчёта нужна, если подходящего метода или данных пока нет: гипотеза перейдёт в «проверяется», а расчёт
              добавите позже.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
