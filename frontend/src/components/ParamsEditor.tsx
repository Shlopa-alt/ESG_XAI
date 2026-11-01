import { useQuery } from "@tanstack/react-query";

export interface MethodParam {
  name: string;
  label: string;
  default: unknown;
  min: number;
  max: number;
  kind: "int" | "column" | "columns" | "sheet";
  numeric: boolean;
  required: boolean;
  hint: string;
}

export type ParamValue = number | string | string[];

interface Columns {
  columns: string[];
  numeric: string[];
  sheets: string[]; // листы-таблицы книги Excel; у CSV — пусто
  sheet: string;
}

async function snapshotColumns(id: number, sheet: string): Promise<Columns> {
  const q = sheet ? `?sheet=${encodeURIComponent(sheet)}` : "";
  const res = await fetch(`/api/snapshots/${id}/columns${q}`, { credentials: "same-origin" });
  const body = (await res.json().catch(() => null)) as (Columns & { detail?: string }) | null;
  if (!res.ok || !body) throw new Error(body?.detail ?? `Ошибка ${res.status}`);
  return body;
}

/** Значения по умолчанию, поверх — то, что уже есть (например, предложение Qwen). */
export function defaults(params: MethodParam[], given: Record<string, unknown> = {}): Record<string, ParamValue> {
  return Object.fromEntries(
    params.map((p) => {
      const v = given[p.name] ?? p.default;
      if (p.kind === "int") return [p.name, typeof v === "number" ? v : Number(v ?? p.min)];
      if (p.kind === "column" || p.kind === "sheet") return [p.name, typeof v === "string" ? v : ""];
      return [p.name, Array.isArray(v) ? v.map(String) : []];
    }),
  );
}

/** Параметры метода библиотеки: числа, лист книги Excel и столбцы выбранного среза (из заголовка). */
export function ParamsEditor({
  params,
  snapshotId,
  value,
  onChange,
  idPrefix,
}: {
  params: MethodParam[];
  snapshotId: number | null;
  value: Record<string, ParamValue>;
  onChange: (v: Record<string, ParamValue>) => void;
  idPrefix: string;
}) {
  const needColumns = params.some((p) => p.kind !== "int");
  const sheetParam = params.find((p) => p.kind === "sheet");
  const sheet = sheetParam ? String(value[sheetParam.name] ?? "") : "";
  const cols = useQuery({
    queryKey: ["snapshot-columns", snapshotId, sheet],
    queryFn: () => snapshotColumns(snapshotId as number, sheet),
    enabled: needColumns && snapshotId !== null,
    staleTime: 300_000,
  });
  const set = (name: string, v: ParamValue) => onChange({ ...value, [name]: v });
  // другой лист — другие столбцы: выбранные раньше сбрасываются
  const setSheet = (name: string, v: string) =>
    onChange({
      ...Object.fromEntries(
        params.map((p) => [p.name, p.kind === "column" ? "" : p.kind === "columns" ? [] : (value[p.name] ?? "")]),
      ),
      [name]: v,
    });
  const options = (p: MethodParam) => (p.numeric ? (cols.data?.numeric ?? []) : (cols.data?.columns ?? []));
  return (
    <div className="params-editor">
      {needColumns && cols.isError && (
        <p className="error" role="alert">
          {cols.error.message}
        </p>
      )}
      {needColumns && snapshotId === null && <p className="muted">Выберите срез — появятся его столбцы.</p>}
      <div className="form-grid">
        {params.map((p) => {
          const id = `${idPrefix}-${p.name}`;
          if (p.kind === "sheet") {
            const sheets = cols.data?.sheets ?? [];
            if (sheets.length === 0) return null; // CSV — листов нет
            return (
              <label key={p.name} className="field span-2" htmlFor={id}>
                {p.label}
                <select id={id} value={String(value[p.name] || cols.data?.sheet || "")} onChange={(e) => setSheet(p.name, e.target.value)}>
                  {sheets.map((sh) => (
                    <option key={sh} value={sh}>
                      {sh}
                    </option>
                  ))}
                </select>
              </label>
            );
          }
          if (p.kind === "int") {
            return (
              <label key={p.name} className="field" htmlFor={id}>
                {p.label}
                <input
                  id={id}
                  type="number"
                  min={p.min}
                  max={p.max}
                  step={1}
                  required
                  value={String(value[p.name] ?? "")}
                  onChange={(e) => set(p.name, Number(e.target.value))}
                />
              </label>
            );
          }
          if (p.kind === "column") {
            return (
              <label key={p.name} className="field span-2" htmlFor={id}>
                {p.label}
                <select id={id} value={String(value[p.name] ?? "")} onChange={(e) => set(p.name, e.target.value)} required={p.required}>
                  <option value="">— выберите столбец —</option>
                  {options(p).map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
            );
          }
          const chosen = new Set(Array.isArray(value[p.name]) ? (value[p.name] as string[]) : []);
          return (
            <fieldset key={p.name} className="field span-2 columns-pick">
              <legend>
                {p.label}
                {p.hint && <span className="muted"> — {p.hint}</span>} · выбрано {chosen.size}
              </legend>
              <div className="columns-list">
                {options(p).map((c) => (
                  <label key={c} className="check">
                    <input
                      type="checkbox"
                      checked={chosen.has(c)}
                      onChange={(e) => {
                        const next = new Set(chosen);
                        if (e.target.checked) next.add(c);
                        else next.delete(c);
                        set(p.name, options(p).filter((x) => next.has(x)));
                      }}
                    />{" "}
                    {c}
                  </label>
                ))}
                {cols.isSuccess && options(p).length === 0 && <span className="muted">Подходящих столбцов нет.</span>}
              </div>
            </fieldset>
          );
        })}
      </div>
    </div>
  );
}
