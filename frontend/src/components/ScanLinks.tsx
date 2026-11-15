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
  reason?: "" | "not_confirmed" | "no_data";
}

const num = (v: number | null) => (v === null ? "—" : v.toLocaleString("ru-RU", { maximumFractionDigits: 2, signDisplay: "exceptZero" }));
// ξ — от 0 до 1, знака у неё нет
const plain = (v: number | null) => (v === null ? "—" : v.toLocaleString("ru-RU", { maximumFractionDigits: 2 }));
const asLinks = (v: unknown): ScanLink[] => (Array.isArray(v) ? (v as ScanLink[]).filter((x) => x && typeof x.a === "string") : []);

/** Черновик идеи по связи: человек допишет и решит, отправлять ли. Связь — не причина. */
export function ideaDraft(l: ScanLink, run: Pick<RunRow, "id" | "experiment" | "dataset">): NonNullable<ProposeState["draft"]> {
  const monotone = l.kind === "монотонная";
  const where = [run.experiment, run.dataset].filter(Boolean).join(", ");
  return {
    title: `Связь «${l.a}» и «${l.b}» сохраняется на других данных`,
    statement: monotone
      ? `Чем больше «${l.a}», тем ${(l.rho_confirm ?? l.rho) > 0 ? "больше" : "меньше"} «${l.b}» — и это сохраняется на других данных.`
      : `«${l.b}» зависит от «${l.a}» немонотонно (например, U-образно или с порогом) — какая это зависимость и сохраняется ли она на других данных.`,
    rationale:
      `Найдено поиском связей${where ? ` (${where}, расчёт № ${run.id})` : ""}: ` +
      (monotone
        ? `ρ Спирмена на части поиска ${num(l.rho)}, на отложенной части ${num(l.rho_confirm)}.`
        : `ξ Чаттерджи на части поиска ${plain(l.xi)}, на отложенной части ${plain(l.xi_confirm)}.`) +
      " Это связь, а не причина: она может объясняться третьим показателем.",
  };
}

/** Итоги «Поиска связей» на странице расчёта: подтверждённые связи с переходом к сетям и к идее,
 * и отдельно — не подтвердившиеся (это тоже результат). */
const strength = (l: ScanLink, part: "find" | "confirm") =>
  l.kind === "немонотонная"
    ? `ξ ${part === "find" ? "на части поиска" : "на отложенной части"} ${plain(part === "find" ? l.xi : l.xi_confirm)}`
    : `ρ ${part === "find" ? "на части поиска" : "на отложенной части"} ${num(part === "find" ? l.rho : l.rho_confirm)}`;

const total = (v: unknown, shown: number) => (typeof v === "number" && v > shown ? ` · показано ${shown} из ${v}` : "");

export function ScanLinks({ run }: { run: RunRow }) {
  const navigate = useNavigate();
  const links = asLinks(run.summary.links);
  const missed = asLinks(run.summary.not_confirmed);
  const same = Array.isArray(run.summary.same_pairs) ? (run.summary.same_pairs as Array<{ a: string; b: string }>) : [];
  const rowsConfirm = typeof run.summary.rows_confirm === "number" ? run.summary.rows_confirm : null;
  if (run.status !== "done") return null;
  return (
    <section className="card scan-links">
      <h2 className="h2">Найденные связи{total(run.summary.links_total, links.length)}</h2>
      <p className="muted field-hint">
        ρ — сила и направление связи от −1 до 1 («чем больше одно, тем больше другое» или наоборот); ξ — сила любой
        зависимости от 0 до 1, в том числе немонотонной (U-образной, пороговой).
      </p>
      {links.length > 0 && (
        <p className="muted">
          Каждая связь подтвердилась на отложенной части данных — той, где её не искали. Это кандидат в идею, а не
          вывод: связь не говорит, что из чего следует. Предложите её идеей — дальше обычный путь через рецензию.
        </p>
      )}
      {links.length === 0 ? (
        <p>
          Ни одна связь не подтвердилась на отложенной части{rowsConfirm !== null ? ` (${rowsConfirm} строк)` : ""}. Это
          результат: на этих данных устойчивых связей не нашлось. Это не доказывает, что их нет: при небольшом числе
          строк слабые связи не видны.
        </p>
      ) : (
        <ul className="list scan-list">
          {links.map((l) => (
            <li key={`${l.a}|${l.b}`}>
              <div>
                <strong>
                  «{l.a}» — «{l.b}»
                </strong>{" "}
                <span className="muted">
                  · {l.kind} · {strength(l, "confirm")}
                </span>
              </div>
              <div className="review-form">
                {run.snapshot_id !== null && (
                  <Link
                    className="btn-ghost"
                    to={`/analysis?${new URLSearchParams({ snapshot: String(run.snapshot_id), target: l.b }).toString()}`}
                    title={`Откроет «Анализ данных»: насколько «${l.b}» предсказуем по остальным столбцам. Это не проверка самой связи.`}
                  >
                    Предсказать «{l.b}» нейросетями по остальным столбцам
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
        <details open={missed.length < 10}>
          <summary>
            Не подтвердились на отложенной части · {missed.length}
            {total(run.summary.not_confirmed_total, missed.length)}
          </summary>
          <p className="muted">
            Были видны на части поиска и не подтвердились на другой — чаще всего это случайность. Это тоже результат: брать
            их в идеи не стоит.
          </p>
          <ul className="list">
            {missed.map((l) => (
              <li key={`${l.a}|${l.b}`}>
                «{l.a}» — «{l.b}» <span className="muted">· {l.kind} · {strength(l, "find")}</span>
                {l.reason === "no_data" && <span className="muted"> · на отложенной части не хватило строк, чтобы проверить</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {same.length > 0 && (
        <p className="muted">
          Почти совпадают (|ρ| ≥ 0,98) — возможно, это один показатель или соседние годы одного; связи второго столбца пары
          не искались: {same.map((x) => `«${x.a}» и «${x.b}»`).join(", ")}.
        </p>
      )}
    </section>
  );
}
