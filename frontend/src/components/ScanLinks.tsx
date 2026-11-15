import { Link, useNavigate } from "react-router-dom";

import type { ProposeState } from "../pages/HypothesesPage";
import type { RunRow } from "../pages/RunPage";

/** Связь из итогов «Поиска связей» (runner/methods/correlation_scan.py: summary.links). */
export interface ScanLink {
  a: string;
  b: string;
  kind: string; // «монотонная» | «немонотонная»
  rho: number;
  xi: number;
  rho_confirm: number | null;
  xi_confirm: number | null;
  n: number;
}

const num = (v: number | null) => (v === null ? "—" : v.toLocaleString("ru-RU", { maximumFractionDigits: 2, signDisplay: "exceptZero" }));
const asLinks = (v: unknown): ScanLink[] => (Array.isArray(v) ? (v as ScanLink[]).filter((x) => x && typeof x.a === "string") : []);

/** Черновик идеи по связи: человек допишет и решит, отправлять ли. Связь — не причина. */
export function ideaDraft(l: ScanLink, run: Pick<RunRow, "id" | "experiment" | "dataset">): NonNullable<ProposeState["draft"]> {
  const monotone = l.kind === "монотонная";
  const where = [run.experiment, run.dataset].filter(Boolean).join(", ");
  return {
    title: `«${l.a}» и «${l.b}» связаны`,
    statement: monotone
      ? `Чем больше «${l.a}», тем ${(l.rho_confirm ?? l.rho) > 0 ? "больше" : "меньше"} «${l.b}» — и это сохраняется на других данных.`
      : `«${l.b}» зависит от «${l.a}» немонотонно (например, U-образно или с порогом) — какая это зависимость и сохраняется ли она на других данных.`,
    rationale:
      `Найдено поиском связей${where ? ` (${where}, расчёт № ${run.id})` : ""}: ` +
      (monotone
        ? `ρ Спирмена на части поиска ${num(l.rho)}, на отложенной части ${num(l.rho_confirm)}.`
        : `ξ Чаттерджи на части поиска ${num(l.xi)}, на отложенной части ${num(l.xi_confirm)}.`) +
      " Это связь, а не причина: она может объясняться третьим показателем.",
  };
}

/** Итоги «Поиска связей» на странице расчёта: подтверждённые связи с переходом к сетям и к идее,
 * и отдельно — не подтвердившиеся (это тоже результат). */
export function ScanLinks({ run }: { run: RunRow }) {
  const navigate = useNavigate();
  const links = asLinks(run.summary.links);
  const missed = asLinks(run.summary.not_confirmed);
  if (run.status !== "done") return null;
  return (
    <section className="card scan-links">
      <h2 className="h2">Найденные связи</h2>
      <p className="muted">
        Каждая связь подтвердилась на отложенной части данных — той, где её не искали. Это кандидат в идею, а не вывод:
        связь не говорит, что из чего следует. Проверьте её разными сетями или предложите идеей — дальше обычный путь
        через рецензию.
      </p>
      {links.length === 0 ? (
        <p>Ни одна связь не подтвердилась на отложенной части. Это тоже результат: на этих данных неочевидных связей нет.</p>
      ) : (
        <ul className="list scan-list">
          {links.map((l) => (
            <li key={`${l.a}|${l.b}`}>
              <div>
                <strong>
                  «{l.a}» — «{l.b}»
                </strong>{" "}
                <span className="muted">
                  · {l.kind}
                  {l.kind === "монотонная"
                    ? ` · ρ на отложенной части ${num(l.rho_confirm)}`
                    : ` · ξ на отложенной части ${num(l.xi_confirm)}`}
                </span>
              </div>
              <div className="review-form">
                {run.snapshot_id !== null && (
                  <Link
                    className="btn-ghost"
                    to={`/analysis?${new URLSearchParams({ snapshot: String(run.snapshot_id), target: l.b }).toString()}`}
                  >
                    Проверить разными сетями: «{l.b}» по данным
                  </Link>
                )}
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => navigate("/hypotheses", { state: { draft: ideaDraft(l, run) } satisfies ProposeState })}
                >
                  Предложить идеей
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {missed.length > 0 && (
        <details>
          <summary>Не подтвердились на отложенной части · {missed.length}</summary>
          <p className="muted">Были видны на части поиска и пропали на другой — скорее всего, случайность. Брать их в идеи не стоит.</p>
          <ul className="list">
            {missed.map((l) => (
              <li key={`${l.a}|${l.b}`}>
                «{l.a}» — «{l.b}» <span className="muted">· ρ на части поиска {num(l.rho)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
