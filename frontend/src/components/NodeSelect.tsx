import { useQuery } from "@tanstack/react-query";

import { getMethodology, KIND_LABEL } from "../api/methodology";

/** Выбор узла методики (направление, вариант, задание), к которому относится работа. */
export function NodeSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const m = useQuery({ queryKey: ["methodology"], queryFn: getMethodology });
  const nodes = (m.data?.sections ?? []).filter((n) => n.kind !== "section");
  const depth = (n: string) => n.split(".").length - 1;
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">— не относится к заданию методики —</option>
      {nodes.map((n) => (
        <option key={n.number} value={n.number}>
          {"  ".repeat(depth(n.number))}
          {n.number} · {KIND_LABEL[n.kind]} · {n.title}
        </option>
      ))}
    </select>
  );
}
