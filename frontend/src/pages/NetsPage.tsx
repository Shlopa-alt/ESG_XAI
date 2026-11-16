import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ManualMode } from "../components/ManualMode";

import { checkLink, getLinks, launchAnalysis, recommend, type LinkCheck, type LinksOut, type NetResult, type ScanOut } from "../api/analysis";
import { useMe } from "../auth/useAuth";
import type { ParamValue } from "../components/ParamsEditor";
import { ideaDraft } from "../components/ScanLinks";
import { NetsTabs } from "../components/SectionTabs";
import { canRun, plural, Stepper } from "../components/Ux";
import { CatalogTable } from "./AnalysisPage";
import type { ProposeState } from "./HypothesesPage";
import { listTemplates, type RunTemplate } from "./RunPage";

/** Набор сетей проверки связи — в том порядке, в каком их считает бэкенд (app/api/analysis.py: NET_SET). */
const NETS = [
  { key: "mlp", short: "Перцептрон" },
  { key: "transformer", short: "Трансформер" },
  { key: "gbm", short: "Бустинг" },
  { key: "linear", short: "Линейная" },
];
const ACTIVE = new Set(["queued", "running"]);
const STATUS: Record<string, string> = {
  queued: "в очереди",
  running: "считается",
  failed: "сбой",
  stopped: "остановлен",
  skipped: "не запускалась",
};
const r2 = (v: number | null) => (v === null ? "—" : v.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pairOf = (a: string, b: string) => [a, b].sort().join("\u0000");
type ScanLinkRow = ScanOut["links"][number];

function busy(d: LinksOut | undefined): boolean {
  if (!d) return false;
  return (d.scan !== null && ACTIVE.has(d.scan.status)) || d.checks.some((c) => c.nets.some((n) => ACTIVE.has(n.status)));
}

/** Ячейка «сеть × связь»: R² на данных, которых не было в обучении, и держится ли связь. */
function NetCell({ n, label }: { n: NetResult | undefined; label: string }) {
  // на узком экране строка — карточка: подпись ячейки берётся из data-label, пустые ячейки скрыты
  if (!n) {
    return (
      <td className="num muted net-empty" data-label={label}>
        —
      </td>
    );
  }
  if (n.holds === null) {
    return (
      <td className="num muted" data-label={label} title={n.reason || undefined}>
        {STATUS[n.status] ?? n.status}
        {n.reason && <span className="sr-only">: {n.reason}</span>}
      </td>
    );
  }
  const text = `R² ${r2(n.r2)}, на перемешанной цели ${r2(n.placebo)} — ${n.holds ? "держится" : "не держится"}`;
  return (
    <td className={n.holds ? "num net-holds" : "num net-fails"} data-label={label} title={text}>
      <span aria-hidden="true">
        {r2(n.r2)} {n.holds ? "✓" : "✗"}
      </span>
      <span className="sr-only">{text}</span>
    </td>
  );
}

function Verdict({ c }: { c: LinkCheck }) {
  const link = (
    <Link to={`/experiments/${c.experiment}`} className="mono">
      {c.experiment}
    </Link>
  );
  if (c.finished < c.total) {
    return (
      <>
        <span className="badge st-running">считается</span> {link}
      </>
    );
  }
  const cls = c.held === 0 ? "badge st-failed" : c.held === c.finished ? "badge st-done" : "badge st-review";
  return (
    <>
      <span className={cls}>{c.held === 0 ? "не держится" : `держится у ${c.held} из ${c.finished}`}</span> {link}
    </>
  );
}

/** Строка таблицы: связь, что предсказываем, итог каждой сети; без проверки — кнопка «Проверить сетями». */
type Column = { key: string; short: string };

/** Столбцы сетей: встроенный набор и методы из статей, которые уже считались в проверках. */
function columnsOf(checks: LinkCheck[]): Column[] {
  const extra = new Map<string, string>();
  for (const c of checks) for (const n of c.nets) if (!NETS.some((x) => x.key === n.net)) extra.set(n.net, n.title);
  return [...NETS, ...[...extra].map(([key, title]) => ({ key, short: title.length > 18 ? `${title.slice(0, 17)}…` : title }))];
}

function LinkRow({ l, check, scan, canLaunch, columns }: {
  l: ScanLinkRow;
  check: LinkCheck | undefined;
  scan: ScanOut;
  canLaunch: boolean;
  columns: Column[];
}) {
  const qc = useQueryClient();
  const [target, setTarget] = useState(l.b);
  const go = useMutation({
    mutationFn: () => checkLink({ scan_run: scan.run_id, a: l.a, b: l.b, target, node: "" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["links"] });
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const byNet = new Map((check?.nets ?? []).map((n) => [n.net, n]));
  const strength = l.kind === "немонотонная" ? `немонотонная, ξ ${r2(l.xi_confirm)}` : `ρ ${r2(l.rho_confirm)}`;
  const selectId = `t-${l.a}-${l.b}`;
  return (
    <tr>
      <th scope="row">
        <span className="net-pair">«{l.a}»</span> <span className="net-pair">— «{l.b}»</span>
        <div className="muted net-sub">{strength}</div>
      </th>
      {columns.map((n) => (
        <NetCell key={n.key} n={byNet.get(n.key)} label={n.short} />
      ))}
      <td data-label="Проверка" className="net-action">
        {check ? (
          <>
            <div className="muted net-sub">предсказывали «{check.target}»</div>
            <Verdict c={check} />
          </>
        ) : canLaunch ? (
          <>
            <label className="net-sub muted" htmlFor={selectId}>
              Что предсказываем<span className="sr-only"> в связи «{l.a}» — «{l.b}»</span>
            </label>
            <select id={selectId} value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value={l.b}>{l.b}</option>
              <option value={l.a}>{l.a}</option>
            </select>
            <button type="button" className="btn-ghost" disabled={go.isPending} onClick={() => go.mutate()}>
              {go.isPending ? "Ставлю расчёты…" : "Проверить сетями"}
            </button>
            {go.isError && (
              <p className="error" role="alert">
                {go.error.message}
              </p>
            )}
          </>
        ) : (
          <span className="muted">не проверялась</span>
        )}
      </td>
    </tr>
  );
}

export function Nets() {
  const me = useMe();
  const canLaunch = canRun(me.data?.role);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const templates = useQuery({ queryKey: ["run-templates"], queryFn: listTemplates });
  // версии данных-таблиц: их видят общие методы библиотеки
  const snapshots = useMemo(() => {
    const seen = new Map<number, RunTemplate["snapshots"][number]>();
    for (const t of templates.data ?? []) if (t.scope === "generic") for (const s of t.snapshots) seen.set(s.id, s);
    return [...seen.values()];
  }, [templates.data]);
  const snapshot = Number(search.get("snapshot")) || "";
  const links = useQuery({
    queryKey: ["links", snapshot],
    queryFn: () => getLinks(snapshot as number),
    enabled: snapshot !== "",
    retry: false,
    refetchInterval: (q) => (busy(q.state.data) ? 10_000 : false),
  });
  // карточка «Поиск связей» из рекомендации: столбцы и столбец-группа панели — по данным
  const reco = useQuery({
    queryKey: ["analysis", snapshot, "", "", "", ""],
    queryFn: () => recommend({ snapshot_id: snapshot as number, sheet: "", target: "", node: "", hypothesis: "" }),
    enabled: snapshot !== "",
    retry: false,
  });
  const scanRec = reco.data?.recommendations.find((r) => r.template === "correlation-scan");
  const group = typeof scanRec?.params.group === "string" ? scanRec.params.group : "";
  const find = useMutation({
    mutationFn: () => {
      if (!scanRec) throw new Error("Рекомендация ещё не готова");
      return launchAnalysis({
        snapshot_id: snapshot as number,
        template: scanRec.template,
        params: scanRec.params as Record<string, ParamValue>,
        node: "",
        hypothesis: "",
        expected: "",
        choice: { key: scanRec.key, title: scanRec.title, why: scanRec.why, primary: false, net: "", as_authors: false, evidence: "", article: "", task: "scan" },
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["links", snapshot] });
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });

  const d = links.data;
  const scan = d?.scan ?? null;
  const scanDone = scan?.status === "done";
  // проверка связи: последняя по этой паре показателей
  const checks = new Map<string, LinkCheck>();
  for (const c of d?.checks ?? []) checks.set(pairOf(c.a, c.b), c);
  const columns = columnsOf(d?.checks ?? []);
  const finished = (d?.checks ?? []).filter((c) => c.total > 0 && c.finished === c.total);
  const step = snapshot === "" ? 0 : !scanDone ? 1 : finished.length === 0 ? 2 : 3;
  const findButton = (label: string, primary: boolean) =>
    canLaunch && (
      <button
        type="button"
        className={primary ? "btn-primary" : "btn-ghost"}
        disabled={find.isPending || !scanRec?.runnable}
        onClick={() => find.mutate()}
      >
        {find.isPending ? "Ставлю расчёт…" : label}
      </button>
    );

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">НЕЙРОСЕТИ</span>
        <h1 className="page-title">Нейросети</h1>
        <p className="lead">
          Найдите связи в данных и проверьте каждую разными нейросетями. Связь, которая держится у нескольких сетей на
          данных, которых не было в обучении, — кандидат в идею, а через неё — в изменение методики.
        </p>
      </section>
      <NetsTabs />
      <Stepper steps={["Данные", "Найти связи", "Проверить сетями", "В методику"]} current={step} label="Путь от данных к методике" />

      <section className="card wizard" aria-labelledby="nets-1">
        <h2 className="h2" id="nets-1">
          1. Данные
        </h2>
        <label className="field" htmlFor="nets-snap">
          Набор данных и версия
          <select
            id="nets-snap"
            value={snapshot}
            onChange={(e) => setSearch(e.target.value ? { snapshot: e.target.value } : {}, { replace: true })}
          >
            <option value="">— выберите —</option>
            {snapshots.map((s) => (
              <option key={s.id} value={s.id}>
                {s.dataset} · {s.version}
                {s.row_count ? ` · ${s.row_count} строк` : ""}
              </option>
            ))}
          </select>
        </label>
        {templates.isSuccess && snapshots.length === 0 && (
          <p className="muted">
            Версий данных-таблиц пока нет — загрузите файл в разделе <Link to="/data">«Данные»</Link>.
          </p>
        )}
        {reco.data && (
          <p className="muted">
            {reco.data.rows !== null && `${reco.data.rows} строк, `}
            {plural(reco.data.numeric.length, "числовой показатель", "числовых показателя", "числовых показателей")}.
            {group && ` Строки повторяются по годам: каждая «${group}» — одно наблюдение, данные по ней усредняются.`}
          </p>
        )}
        {snapshot !== "" && <ManualMode snapshot={snapshot} />}
        {(reco.isError || links.isError) && (
          <p className="error" role="alert">
            {(reco.error ?? links.error)?.message}
          </p>
        )}
      </section>

      {snapshot !== "" && d && (
        <section className="card wizard" aria-labelledby="nets-2">
          <h2 className="h2" id="nets-2">
            2. Найти связи
          </h2>
          <p className="muted">
            Платформа переберёт все пары показателей и оставит только связи, которые подтвердились на части данных, где их
            не искали.
          </p>
          {scan === null && (
            <div>
              {findButton("Найти связи", true)}
              {!canLaunch && <p className="muted">Запускать поиск могут исследователи.</p>}
            </div>
          )}
          {scan !== null && ACTIVE.has(scan.status) && (
            <p>
              Идёт поиск связей — расчёт <Link to={`/run/${scan.run_id}`}>№ {scan.run_id}</Link>, {STATUS[scan.status]}. Страница
              обновится сама.
            </p>
          )}
          {scan !== null && (scan.status === "failed" || scan.status === "stopped") && (
            <>
              <p className="error" role="alert">
                Поиск связей № {scan.run_id} не закончился{scan.message ? `: ${scan.message}` : "."}
              </p>
              <div>{findButton("Найти связи заново", true)}</div>
            </>
          )}
          {scanDone && scan && (
            <>
              <p>
                Подтверждено <strong>{scan.confirmed ?? 0}</strong> из {scan.pairs ?? "—"} пар показателей
                {scan.unit === "group" && scan.group ? ` (наблюдение — «${scan.group}»)` : ""}.{" "}
                <Link to={`/run/${scan.run_id}`}>Подробнее о поиске № {scan.run_id}</Link>
              </p>
              {scan.panel_hint && (
                <p className="error">
                  Похоже на панель: строки повторяются по «{scan.panel_hint}». Поиск шёл без столбца-группы — связи могли
                  «подтвердиться» на шуме. Найдите связи заново: платформа подставит группу сама.
                </p>
              )}
              <div>{findButton("Искать заново", false)}</div>
            </>
          )}
          {scanRec && !scanRec.runnable && scanRec.warnings.map((w) => <p key={w} className="blockers">{w}</p>)}
          {find.isError && (
            <p className="error" role="alert">
              {find.error.message}
            </p>
          )}
        </section>
      )}

      {scanDone && scan && (
        <section className="card wizard" aria-labelledby="nets-3">
          <h2 className="h2" id="nets-3">
            3. Проверить сетями
          </h2>
          <p className="muted">
            Каждая сеть предсказывает один показатель связи по остальным — на данных, которых не было в обучении. Связь
            держится у сети (✓), если R² выше, чем на перемешанной цели, где связи нет по построению, и выше 0,05.
          </p>
          {scan.links.length === 0 ? (
            <p>Ни одна связь не подтвердилась — проверять сетями нечего. Это тоже результат.</p>
          ) : (
            <div className="table-wrap">
              <table className="table nets-table">
                <caption className="sr-only">Связи из поиска и их проверка сетями</caption>
                <thead>
                  <tr>
                    <th scope="col">Связь</th>
                    {columns.map((n) => (
                      <th key={n.key} scope="col" className="num">
                        {n.short}
                      </th>
                    ))}
                    <th scope="col">Проверка</th>
                  </tr>
                </thead>
                <tbody>
                  {scan.links.map((l) => (
                    <LinkRow
                      key={pairOf(l.a, l.b)}
                      l={l}
                      check={checks.get(pairOf(l.a, l.b))}
                      scan={scan}
                      canLaunch={canLaunch}
                      columns={columns}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {scanDone && scan && finished.length > 0 && d && (
        <section className="card wizard" aria-labelledby="nets-4">
          <h2 className="h2" id="nets-4">
            4. В методику
          </h2>
          <p className="muted">
            Связь, которая держится у нескольких сетей, — кандидат в идею. Дальше обычный путь: рецензент решает, стоит ли
            проверять, идёт проверка, и по её итогу — предложение изменить методику.
          </p>
          <ul className="list">
            {finished.map((c) => {
              const l = scan.links.find((x) => pairOf(x.a, x.b) === pairOf(c.a, c.b));
              const nets = c.nets.filter((n) => n.holds !== null).map((n) => `${n.title}: R² ${r2(n.r2)}`).join("; ");
              return (
                <li key={c.experiment} className="nets-idea">
                  <span>
                    «{c.a}» — «{c.b}»: {c.held === 0 ? "не держится ни у одной сети" : `держится у ${c.held} из ${c.finished} сетей`}
                  </span>
                  {c.held > 0 && l ? (
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => {
                        const draft = ideaDraft(l, { id: scan.run_id, experiment: c.experiment, dataset: d.snapshot.dataset });
                        draft.rationale += ` Проверка сетями (${c.experiment}), предсказывали «${c.target}»: держится у ${c.held} из ${c.finished} — ${nets}.`;
                        navigate("/hypotheses", { state: { draft } satisfies ProposeState });
                      }}
                    >
                      Предложить идеей
                    </button>
                  ) : (
                    <span className="muted"> — это тоже результат; в идеи такую связь не берём.</span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <CatalogTable />
    </>
  );
}
