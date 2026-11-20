import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { listDatasets } from "../api/experiments";
import type { ComponentSchema, ParamSchema } from "../api/studio";

type Values = Record<string, unknown>;

interface SnapshotRow {
  id: number;
  version: string;
  row_count: number | null;
}

async function datasetSnapshots(code: string): Promise<SnapshotRow[]> {
  const res = await fetch(`/api/datasets/${encodeURIComponent(code)}`, { credentials: "same-origin" });
  if (!res.ok) return [];
  const body = (await res.json()) as { snapshots?: SnapshotRow[] };
  return body.snapshots ?? [];
}

/** Версия набора данных: сначала набор, потом его версия. В параметрах — snapshot_id и код набора. */
function SnapshotPicker({ values, onChange, disabled }: { values: Values; onChange: (v: Values) => void; disabled: boolean }) {
  const id = useId();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: listDatasets });
  const code = typeof values.dataset === "string" ? values.dataset : "";
  const snaps = useQuery({ queryKey: ["dataset-snapshots", code], queryFn: () => datasetSnapshots(code), enabled: code !== "" });
  const list = Array.isArray(datasets.data) ? datasets.data : [];
  const versions = Array.isArray(snaps.data) ? snaps.data : [];
  return (
    <>
      <label className="field" htmlFor={`${id}-ds`}>
        Набор данных
        <select
          id={`${id}-ds`}
          value={code}
          disabled={disabled}
          onChange={(e) => onChange({ ...values, dataset: e.target.value, snapshot_id: null })}
        >
          <option value="">— выберите —</option>
          {list.map((d) => (
            <option key={d.code} value={d.code}>
              {d.code} · {d.title}
            </option>
          ))}
        </select>
      </label>
      <label className="field" htmlFor={`${id}-v`}>
        Версия набора
        <select
          id={`${id}-v`}
          value={values.snapshot_id == null ? "" : String(values.snapshot_id)}
          disabled={disabled || code === ""}
          onChange={(e) => onChange({ ...values, snapshot_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">— выберите —</option>
          {versions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.version}
              {s.row_count != null ? ` · ${s.row_count} строк` : ""}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

/** Столбцы текстом через запятую: в поле — набранное как есть (иначе запятую не напечатать). */
function ColumnsText({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: string[];
  disabled: boolean;
  onChange: (v: string[]) => void;
}) {
  const [raw, setRaw] = useState(value.join(", "));
  return (
    <label className="field" htmlFor={id}>
      {label}
      <input
        id={id}
        value={raw}
        disabled={disabled}
        placeholder="через запятую; или посчитайте узел перед этим — появится список"
        onChange={(e) => {
          setRaw(e.target.value);
          onChange(
            e.target.value
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
          );
        }}
      />
    </label>
  );
}

/** Что ещё нужно полям: другие узлы сценария (Узел-ссылка) и сценарии (Подмодель, Цикл). */
export interface ParamContext {
  nodes: { id: string; label: string }[];
  scenarios: { code: string; title: string }[];
}

const NO_CONTEXT: ParamContext = { nodes: [], scenarios: [] };

/** Одно поле параметра по его виду; columns — столбцы, пришедшие на вход from_port (если известны). */
function Field({
  p,
  value,
  onChange,
  columns,
  disabled,
  ctx = NO_CONTEXT,
}: {
  p: ParamSchema;
  value: unknown;
  onChange: (v: unknown) => void;
  columns: (port: string) => string[];
  disabled: boolean;
  ctx?: ParamContext;
}) {
  const id = useId();
  const label = `${p.label}${p.required ? " *" : ""}`;
  const known = columns(p.from_port ?? "in");
  if (p.kind === "node" || p.kind === "scenario") {
    const opts = p.kind === "node" ? ctx.nodes.map((n) => ({ value: n.id, label: n.label })) : ctx.scenarios.map((x) => ({ value: x.code, label: `${x.code} · ${x.title}` }));
    return (
      <label className="field" htmlFor={id}>
        {label}
        <select id={id} value={value == null ? "" : String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">— выберите —</option>
          {opts.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (p.kind === "nodes") {
    const cur = asList(value);
    return (
      <fieldset className="field checks" disabled={disabled}>
        <legend>{label}</legend>
        {ctx.nodes.map((n) => (
          <label key={n.id} className="check">
            <input type="checkbox" checked={cur.includes(n.id)} onChange={(e) => onChange(e.target.checked ? [...cur, n.id] : cur.filter((x) => x !== n.id))} /> {n.label}
          </label>
        ))}
      </fieldset>
    );
  }
  if (p.kind === "code") {
    return (
      <label className="field" htmlFor={id}>
        {label}
        <textarea id={id} className="mono code-input" rows={12} spellCheck={false} wrap="off" value={value == null ? "" : String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
        <span className="muted small">df, df2 — входы, vars — переменные, pd и np уже есть; результат положите в out.</span>
      </label>
    );
  }
  if (p.kind === "bool") {
    return (
      <label className="check">
        <input type="checkbox" checked={value === true} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /> {p.label}
      </label>
    );
  }
  if (p.kind === "select" || (p.kind === "column" && known.length > 0)) {
    const opts = p.kind === "select" ? (p.options ?? []) : known.map((c) => ({ value: c, label: c }));
    const cur = value == null ? "" : String(value);
    return (
      <label className="field" htmlFor={id}>
        {label}
        <select id={id} value={cur} disabled={disabled} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">{p.required ? "— выберите —" : "—"}</option>
          {cur && !opts.some((o) => o.value === cur) && <option value={cur}>{cur} (нет на входе)</option>}
          {opts.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (p.kind === "multiselect" || (p.kind === "columns" && known.length > 0)) {
    const opts = p.kind === "multiselect" ? (p.options ?? []) : known.map((c) => ({ value: c, label: c }));
    const cur = asList(value);
    return (
      <fieldset className="field checks" disabled={disabled}>
        <legend>{label}</legend>
        {opts.map((o) => (
          <label key={o.value} className="check">
            <input
              type="checkbox"
              checked={cur.includes(o.value)}
              onChange={(e) => onChange(e.target.checked ? [...cur, o.value] : cur.filter((x) => x !== o.value))}
            />{" "}
            {o.label}
          </label>
        ))}
      </fieldset>
    );
  }
  if (p.kind === "columns") {
    // столбцы входа ещё не известны (узел перед ним не считали) — через запятую
    return <ColumnsText id={id} label={label} value={asList(value)} disabled={disabled} onChange={onChange} />;
  }
  if (p.kind === "expr") {
    return (
      <label className="field" htmlFor={id}>
        {label}
        <textarea id={id} className="mono" rows={2} value={value == null ? "" : String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
        <span className="muted small">
          {p.hint ?? "Формула: столбцы, + − * /, ЕСЛИ(усл; да; нет), И, ИЛИ, НЕ, ГОД(дата)…"}
          {known.length > 0 ? ` Столбцы: ${known.join(", ")}.` : ""}
        </span>
      </label>
    );
  }
  if (p.kind === "rows") {
    const rows = Array.isArray(value) ? (value as Values[]) : [];
    const fields = p.fields ?? [];
    const blank = () => Object.fromEntries(fields.filter((f) => f.default !== undefined).map((f) => [f.name, f.default]));
    return (
      <fieldset className="field rows" disabled={disabled}>
        <legend>{label}</legend>
        {rows.map((row, i) => (
          <div className="param-row" key={i}>
            {fields.map((f) => (
              <Field
                key={f.name}
                p={f}
                value={row[f.name]}
                columns={columns}
                ctx={ctx}
                disabled={disabled}
                onChange={(v) => onChange(rows.map((r, j) => (j === i ? { ...r, [f.name]: v } : r)))}
              />
            ))}
            <button type="button" className="btn-ghost" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              Убрать
            </button>
          </div>
        ))}
        <button type="button" className="btn-ghost" onClick={() => onChange([...rows, blank()])}>
          Добавить
        </button>
      </fieldset>
    );
  }
  return (
    <label className="field" htmlFor={id}>
      {label}
      <input
        id={id}
        type={p.kind === "number" ? "number" : "text"}
        value={value == null ? "" : String(value)}
        disabled={disabled}
        onChange={(e) => onChange(p.kind === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value)}
      />
      {p.hint && <span className="muted small">{p.hint}</span>}
    </label>
  );
}

/** Настройки узла: поля по схеме компонента. */
export function StudioParams({
  comp,
  values,
  onChange,
  columns,
  disabled = false,
  context = NO_CONTEXT,
}: {
  comp: ComponentSchema;
  values: Values;
  onChange: (v: Values) => void;
  columns: (port: string) => string[];
  disabled?: boolean;
  context?: ParamContext;
}) {
  return (
    <div className="studio-params">
      {comp.params.map((p) =>
        p.kind === "snapshot" ? (
          <SnapshotPicker key={p.name} values={values} onChange={onChange} disabled={disabled} />
        ) : (
          <Field key={p.name} p={p} value={values[p.name] ?? p.default} columns={columns} ctx={context} disabled={disabled} onChange={(v) => onChange({ ...values, [p.name]: v })} />
        ),
      )}
    </div>
  );
}
