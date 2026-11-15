import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { type ChangeRequest, listCrs } from "../api/methodology";

/** Предложения изменить методику, у которых основание — эта проверка. */
export function useCrsOf(experiment: string): ChangeRequest[] {
  const crs = useQuery({ queryKey: ["crs"], queryFn: listCrs, enabled: experiment !== "" });
  const all = Array.isArray(crs.data) ? crs.data : [];
  return experiment ? all.filter((c) => c.bases.some((b) => b.basis_type === "experiment" && b.ref === experiment)) : [];
}

const STATE: Record<ChangeRequest["status"], string> = {
  proposed: "предложено, ждёт рецензии",
  review: "на рецензии",
  accepted: "принято",
  rejected: "отклонено",
};

/** Чем проверка кончилась для методики: последний шаг цикла «идея → проверка → изменение методики».
 * Нет предложений — показывается обычная подсказка (fallback). */
export function CycleNext({ experiment, fallback }: { experiment: string; fallback: ReactNode }) {
  const crs = useCrsOf(experiment);
  if (crs.length === 0) return <>{fallback}</>;
  const accepted = crs.filter((c) => c.status === "accepted");
  return (
    <>
      {accepted.length > 0 ? "Цикл закрыт: по этой проверке изменена методика — " : "По этой проверке предложено изменить методику — "}
      {crs.map((c, i) => (
        <span key={c.code}>
          {i > 0 && "; "}
          <Link to="/methodology" className="mono">
            {c.code}
          </Link>{" "}
          «{c.title}», {STATE[c.status]}
          {c.status === "accepted" && c.target_version && `, версия методики ${c.target_version}`}
        </span>
      ))}
      .
    </>
  );
}
