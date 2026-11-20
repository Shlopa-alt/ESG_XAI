import { useId, useMemo, useState } from "react";

import type { ColumnStats, NodeView } from "../api/studio";

const W = 640;
const H = 300;
const PAD = { l: 56, r: 36, t: 12, b: 40 };
const fmt = (v: number) => (Math.abs(v) >= 1000 || Number.isInteger(v) ? v.toLocaleString("ru-RU", { maximumFractionDigits: 0 }) : v.toLocaleString("ru-RU", { maximumFractionDigits: 3 }));

function ticks(min: number, max: number, n = 4, whole = false): number[] {
  if (min === max) return [min];
  const t = Array.from({ length: n + 1 }, (_, i) => min + ((max - min) * i) / n);
  // число строк — целое: деления 0, 10, 21… без дробей
  return whole ? [...new Set(t.map((v) => Math.round(v)))] : t;
}

function Axes({ x, y, xLabel, yLabel }: { x: [number, number]; y: [number, number]; xLabel: string; yLabel: string }) {
  const sx = (v: number) => PAD.l + ((v - x[0]) / (x[1] - x[0] || 1)) * (W - PAD.l - PAD.r);
  const sy = (v: number) => H - PAD.b - ((v - y[0]) / (y[1] - y[0] || 1)) * (H - PAD.t - PAD.b);
  return (
    <g className="chart-axes">
      <line x1={PAD.l} y1={H - PAD.b} x2={W - PAD.r} y2={H - PAD.b} />
      <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={H - PAD.b} />
      {ticks(y[0], y[1], 4, yLabel === "строк").map((v) => (
        <g key={`y${v}`}>
          <line x1={PAD.l} x2={W - PAD.r} y1={sy(v)} y2={sy(v)} className="chart-grid" />
          <text x={PAD.l - 6} y={sy(v) + 4} textAnchor="end">
            {fmt(v)}
          </text>
        </g>
      ))}
      {ticks(x[0], x[1]).map((v) => (
        <text key={`x${v}`} x={sx(v)} y={H - PAD.b + 16} textAnchor="middle">
          {fmt(v)}
        </text>
      ))}
      <text x={(PAD.l + W - PAD.r) / 2} y={H - 4} textAnchor="middle" className="chart-label">
        {xLabel}
      </text>
      <text x={12} y={(PAD.t + H - PAD.b) / 2} textAnchor="middle" className="chart-label" transform={`rotate(-90 12 ${(PAD.t + H - PAD.b) / 2})`}>
        {yLabel}
      </text>
    </g>
  );
}

const span = (vals: number[]): [number, number] => {
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  return lo === hi ? [lo - 1, hi + 1] : [lo, hi];
};

type Kind = "hist" | "bar" | "scatter" | "line";

/** Визуализатор «Диаграмма»: гистограмма (по всем строкам), столбцы, точки и линия (по выборке). */
export function StudioChart({ view }: { view: NodeView }) {
  const id = useId();
  const rowsSrc = view.sample ?? view.table;
  const cols = rowsSrc?.columns ?? [];
  const numeric = cols.filter((c) => c.kind === "number" || c.kind === "integer").map((c) => c.name);
  const [kind, setKind] = useState<Kind>("hist");
  const [x, setX] = useState(numeric[0] ?? cols[0]?.name ?? "");
  const [y, setY] = useState(numeric[1] ?? numeric[0] ?? "");
  const idx = (name: string) => cols.findIndex((c) => c.name === name);
  const stat: ColumnStats | undefined = view.statistics?.columns.find((c) => c.name === x);

  const body = useMemo(() => {
    const rows = rowsSrc?.rows ?? [];
    if (kind === "hist") {
      const h = stat?.histogram;
      const first = h?.[0];
      const last = h?.[h.length - 1];
      if (!h || !first || !last) return { empty: "Гистограмма — для числового столбца с разными значениями" };
      const maxC = Math.max(...h.map((b) => b.count));
      const xr: [number, number] = [first.from, last.to];
      return { hist: h, xr, yr: [0, maxC] as [number, number] };
    }
    if (kind === "bar") {
      const i = idx(x);
      const counts = new Map<string, number>();
      rows.forEach((r) => {
        const v = r[i];
        const k = v == null ? "(пусто)" : String(v);
        counts.set(k, (counts.get(k) ?? 0) + 1);
      });
      const bars = [...counts].sort((a, b) => b[1] - a[1]).slice(0, 15);
      return bars.length ? { bars } : { empty: "Нет значений" };
    }
    const i = idx(x);
    const j = idx(y);
    const pts = rows
      .map((r) => [Number(r[i]), Number(r[j])] as [number, number])
      .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && rows.length > 0);
    if (pts.length === 0) return { empty: "Нужны два числовых столбца" };
    if (kind === "line") pts.sort((a, b) => a[0] - b[0]);
    return { pts, xr: span(pts.map((p) => p[0])), yr: span(pts.map((p) => p[1])) };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- idx зависит только от cols
  }, [kind, x, y, rowsSrc, stat]);

  const sx = (v: number, r: [number, number]) => PAD.l + ((v - r[0]) / (r[1] - r[0] || 1)) * (W - PAD.l - PAD.r);
  const sy = (v: number, r: [number, number]) => H - PAD.b - ((v - r[0]) / (r[1] - r[0] || 1)) * (H - PAD.t - PAD.b);
  const total = rowsSrc?.rows.length ?? 0;
  const describe =
    kind === "hist" ? `Гистограмма «${x}» по всем строкам` : kind === "bar" ? `Частота значений «${x}»` : `${kind === "line" ? "Линия" : "Точки"}: «${x}» и «${y}»`;

  return (
    <div className="studio-chart">
      <div className="chart-controls">
        <label className="field inline" htmlFor={`${id}-k`}>
          Вид
          <select id={`${id}-k`} value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            <option value="hist">гистограмма</option>
            <option value="bar">столбцы (частота)</option>
            <option value="scatter">точки</option>
            <option value="line">линия</option>
          </select>
        </label>
        <label className="field inline" htmlFor={`${id}-x`}>
          {kind === "hist" || kind === "bar" ? "Столбец" : "Ось X"}
          <select id={`${id}-x`} value={x} onChange={(e) => setX(e.target.value)}>
            {(kind === "bar" ? cols.map((c) => c.name) : numeric).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        {(kind === "scatter" || kind === "line") && (
          <label className="field inline" htmlFor={`${id}-y`}>
            Ось Y
            <select id={`${id}-y`} value={y} onChange={(e) => setY(e.target.value)}>
              {numeric.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {"empty" in body ? (
        <p className="empty">{body.empty}</p>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={describe}>
          {"hist" in body && body.hist && (
            <>
              <Axes x={body.xr} y={body.yr} xLabel={x} yLabel="строк" />
              {body.hist.map((b) => (
                <rect key={b.from} x={sx(b.from, body.xr) + 1} width={Math.max(1, sx(b.to, body.xr) - sx(b.from, body.xr) - 2)} y={sy(b.count, body.yr)} height={H - PAD.b - sy(b.count, body.yr)} className="chart-bar">
                  <title>{`${fmt(b.from)} … ${fmt(b.to)}: ${b.count}`}</title>
                </rect>
              ))}
            </>
          )}
          {"bars" in body && body.bars && (
            <>
              <Axes x={[0, body.bars.length]} y={[0, Math.max(...body.bars.map((b) => b[1]))]} xLabel={x} yLabel="строк" />
              {body.bars.map(([k, c], i) => {
                const yr: [number, number] = [0, Math.max(...(body.bars ?? []).map((b) => b[1]))];
                const bw = (W - PAD.l - PAD.r) / (body.bars?.length ?? 1);
                return (
                  <rect key={k} x={PAD.l + i * bw + 2} width={Math.max(2, bw - 4)} y={sy(c, yr)} height={H - PAD.b - sy(c, yr)} className="chart-bar">
                    <title>{`${k}: ${c}`}</title>
                  </rect>
                );
              })}
            </>
          )}
          {"pts" in body && body.pts && body.xr && body.yr && (
            <>
              <Axes x={body.xr} y={body.yr} xLabel={x} yLabel={y} />
              {kind === "line" ? (
                <polyline className="chart-line" points={body.pts.map((p) => `${sx(p[0], body.xr as [number, number])},${sy(p[1], body.yr as [number, number])}`).join(" ")} />
              ) : (
                body.pts.map((p, i) => <circle key={i} cx={sx(p[0], body.xr as [number, number])} cy={sy(p[1], body.yr as [number, number])} r={3} className="chart-dot" />)
              )}
            </>
          )}
        </svg>
      )}
      <p className="muted small">
        {kind === "hist"
          ? "По всем строкам результата."
          : view.sample
            ? `По случайной выборке: ${total} строк из ${view.sample.total}.`
            : `По первым ${total} строкам — для выборки из всей таблицы посчитайте этот узел.`}
      </p>
    </div>
  );
}

/** Визуализатор «Качество данных»: пропуски, выбросы, числа текстом, повторы строк. */
export function StudioQuality({ view }: { view: NodeView }) {
  const q = view.quality;
  if (!q) return <p className="empty">Посчитайте узел ещё раз — качество данных появится.</p>;
  return (
    <div className="table-wrap">
      <p className={q.issues ? "error" : "muted"}>
        {q.issues ? `Замечаний: ${q.issues}.` : "Замечаний нет."} Строк: {q.rows}
        {q.duplicate_rows ? `, повторяющихся строк: ${q.duplicate_rows}` : ""}.
      </p>
      <table className="table studio-table">
        <thead>
          <tr>
            <th scope="col">Столбец</th>
            <th scope="col">Тип</th>
            <th scope="col" className="num">Пусто</th>
            <th scope="col" className="num">Различных</th>
            <th scope="col" className="num">Нулей</th>
            <th scope="col" className="num">Отрицательных</th>
            <th scope="col" className="num">Выбросов (1,5·IQR)</th>
            <th scope="col">Замечания</th>
          </tr>
        </thead>
        <tbody>
          {q.columns.map((c) => (
            <tr key={c.name}>
              <th scope="row">{c.name}</th>
              <td>{c.kind}</td>
              <td className="num">
                {c.missing}
                {c.missing ? ` (${Math.round(c.missing_share * 100)}%)` : ""}
              </td>
              <td className="num">{c.unique}</td>
              <td className="num">{c.zeros ?? ""}</td>
              <td className="num">{c.negative ?? ""}</td>
              <td className="num">{c.outliers ?? ""}</td>
              <td className={c.problems.length ? "error" : ""}>{c.problems.join("; ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
