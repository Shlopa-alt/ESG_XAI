import { useState } from "react";

// Графики отчёта эксперимента. Без библиотек: полосы — блоки с позициями в процентах,
// поэтому график сам подстраивается под ширину. Цвета серий — слоты 1–3 проверенной
// категориальной палитры (CSS --series-1..3); подписи — цветом текста, не серии.

export interface BarSpec {
  id: string;
  kind: "bars";
  title: string;
  subtitle?: string;
  unit: string;
  reference?: { value: number; label: string };
  categories: string[];
  series: Array<{ name: string; values: number[] }>;
  interpretation?: string;
}

export interface RangeSpec {
  id: string;
  kind: "ranges";
  title: string;
  subtitle?: string;
  unit: string;
  reference?: { value: number; label: string };
  rows: Array<{ name: string; mean: number; min: number; max: number }>;
  interpretation?: string;
}

export type ChartSpec = BarSpec | RangeSpec;

const fmt = (v: number, unit: string) => {
  if (unit === "%") return `${v.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
  if (Number.isInteger(v)) return v.toLocaleString("ru-RU"); // 0 и целые — без «,00»
  return v.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
};

/** «Красивые» границы и деления оси, включающие ноль и опорную линию. */
function scale(values: number[], ref?: number) {
  const all = [...values, 0, ...(ref === undefined ? [] : [ref])];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  const span = hi - lo || 1;
  const raw = span / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Math.round(t * 1e6) / 1e6);
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  return { pos, ticks };
}

function Axis({ ticks, pos, unit }: { ticks: number[]; pos: (v: number) => number; unit: string }) {
  return (
    <div className="viz-axis" aria-hidden="true">
      {ticks.map((t) => (
        <span key={t} style={{ left: `${pos(t)}%` }}>
          {fmt(t, unit)}
        </span>
      ))}
    </div>
  );
}

function Grid({ ticks, pos, reference }: { ticks: number[]; pos: (v: number) => number; reference?: { value: number } }) {
  return (
    <div className="viz-grid" aria-hidden="true">
      {ticks.map((t) => (
        <i key={t} style={{ left: `${pos(t)}%` }} />
      ))}
      {reference && <b className="viz-ref" style={{ left: `${pos(reference.value)}%` }} />}
    </div>
  );
}

function Legend({ names }: { names: string[] }) {
  return (
    <ul className="viz-legend">
      {names.map((n, i) => (
        <li key={n}>
          <span className={`viz-swatch s${i + 1}`} aria-hidden="true" />
          {n}
        </li>
      ))}
    </ul>
  );
}

function Frame({ spec, legend, table, children }: { spec: ChartSpec; legend?: string[]; table: React.ReactNode; children: React.ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="card viz">
      <div className="viz-head">
        <div>
          <figcaption className="h2 viz-title">{spec.title}</figcaption>
          {spec.subtitle && <p className="muted viz-sub">{spec.subtitle}</p>}
        </div>
        <button type="button" className="btn-ghost viz-toggle" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? "График" : "Таблица"}
        </button>
      </div>
      {legend && legend.length > 1 && <Legend names={legend} />}
      {asTable ? <div className="table-wrap">{table}</div> : children}
      {spec.reference && !asTable && (
        <p className="muted viz-note">
          <span className="viz-ref-key" aria-hidden="true" /> {fmt(spec.reference.value, spec.unit)} — {spec.reference.label}
        </p>
      )}
      {spec.interpretation && <p className="viz-interp">{spec.interpretation}</p>}
    </figure>
  );
}

export function BarChart({ spec }: { spec: BarSpec }) {
  const [hover, setHover] = useState<{ c: number; s: number } | null>(null);
  const { pos, ticks } = scale(spec.series.flatMap((s) => s.values), spec.reference?.value);
  const zero = pos(0);
  const table = (
    <table className="table">
      <thead>
        <tr>
          <th scope="col" />
          {spec.series.map((s) => (
            <th key={s.name} scope="col" className="num">
              {s.name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {spec.categories.map((c, ci) => (
          <tr key={c}>
            <th scope="row">{c}</th>
            {spec.series.map((s) => (
              <td key={s.name} className="num mono">
                {fmt(s.values[ci] ?? 0, spec.unit)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <Frame spec={spec} legend={spec.series.map((s) => s.name)} table={table}>
      <div className="viz-plot" onMouseLeave={() => setHover(null)}>
        {spec.categories.map((c, ci) => (
          <div key={c} className="viz-row">
            <div className="viz-label">{c}</div>
            <div className="viz-track">
              <Grid ticks={ticks} pos={pos} reference={spec.reference} />
              {spec.series.map((s, si) => {
                const v = s.values[ci] ?? 0;
                const left = Math.min(zero, pos(v));
                const width = Math.max(Math.abs(pos(v) - zero), 0.4);
                const active = hover?.c === ci && hover.s === si;
                return (
                  <div key={s.name} className="viz-bar-slot">
                    <span
                      className={`viz-bar s${si + 1}${v < 0 ? " neg" : ""}${active ? " active" : ""}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      tabIndex={0}
                      role="img"
                      aria-label={`${c}, ${s.name}: ${fmt(v, spec.unit)}`}
                      onMouseEnter={() => setHover({ c: ci, s: si })}
                      onFocus={() => setHover({ c: ci, s: si })}
                      onBlur={() => setHover(null)}
                    />
                    {active && (
                      <span className="viz-tip" style={{ left: `${Math.min(Math.max(pos(v), 8), 92)}%` }}>
                        <strong>{fmt(v, spec.unit)}</strong> {s.name}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        <div className="viz-row">
          <div className="viz-label" />
          <Axis ticks={ticks} pos={pos} unit={spec.unit} />
        </div>
      </div>
    </Frame>
  );
}

export function RangeChart({ spec }: { spec: RangeSpec }) {
  const [hover, setHover] = useState<number | null>(null);
  const { pos, ticks } = scale(spec.rows.flatMap((r) => [r.min, r.max]), spec.reference?.value);
  const table = (
    <table className="table">
      <thead>
        <tr>
          <th scope="col" />
          <th scope="col" className="num">Среднее</th>
          <th scope="col" className="num">Худшее</th>
          <th scope="col" className="num">Лучшее</th>
        </tr>
      </thead>
      <tbody>
        {spec.rows.map((r) => (
          <tr key={r.name}>
            <th scope="row">{r.name}</th>
            <td className="num mono">{fmt(r.mean, spec.unit)}</td>
            <td className="num mono">{fmt(r.min, spec.unit)}</td>
            <td className="num mono">{fmt(r.max, spec.unit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <Frame spec={spec} table={table}>
      <div className="viz-plot" onMouseLeave={() => setHover(null)}>
        {spec.rows.map((r, i) => (
          <div key={r.name} className="viz-row with-value">
            <div className="viz-label">{r.name}</div>
            <div className="viz-track">
              <Grid ticks={ticks} pos={pos} reference={spec.reference} />
              <div className="viz-range-slot">
                <span className="viz-whisker" style={{ left: `${pos(r.min)}%`, width: `${pos(r.max) - pos(r.min)}%` }} />
                <span
                  className={`viz-dot${hover === i ? " active" : ""}`}
                  style={{ left: `${pos(r.mean)}%` }}
                  tabIndex={0}
                  role="img"
                  aria-label={`${r.name}: среднее ${fmt(r.mean, spec.unit)}, от ${fmt(r.min, spec.unit)} до ${fmt(r.max, spec.unit)}`}
                  onMouseEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                />
                {hover === i && (
                  <span className="viz-tip" style={{ left: `${Math.min(Math.max(pos(r.mean), 12), 88)}%` }}>
                    среднее <strong>{fmt(r.mean, spec.unit)}</strong> · от {fmt(r.min, spec.unit)} до {fmt(r.max, spec.unit)}
                  </span>
                )}
              </div>
            </div>
            <div className="viz-value mono">{fmt(r.mean, spec.unit)}</div>
          </div>
        ))}
        <div className="viz-row with-value">
          <div className="viz-label" />
          <Axis ticks={ticks} pos={pos} unit={spec.unit} />
          <div className="viz-value muted">среднее</div>
        </div>
      </div>
    </Frame>
  );
}

export function Chart({ spec }: { spec: ChartSpec }) {
  return spec.kind === "ranges" ? <RangeChart spec={spec} /> : <BarChart spec={spec} />;
}
