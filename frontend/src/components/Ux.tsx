import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { HStatus } from "../api/hypotheses";
import type { ExpStatus } from "../api/experiments";
import type { RunRow } from "../pages/RunPage";

/** Человеческое название роли. */
export const ROLE_LABEL: Record<string, { name: string }> = {
  reader: { name: "читатель" },
  researcher: { name: "исследователь" },
  reviewer: { name: "рецензент" },
  owner: { name: "администратор" },
};

/** «1 гипотеза», «3 гипотезы», «5 гипотез». */
export function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10;
  const dd = n % 100;
  const word = d === 1 && dd !== 11 ? one : d >= 2 && d <= 4 && (dd < 12 || dd > 14) ? few : many;
  return `${n} ${word}`;
}

export const canRun = (role: string | undefined) => role === "researcher" || role === "owner";
export const canReview = (role: string | undefined) => role === "reviewer" || role === "owner";

/** Горизонтальный индикатор шагов: пройденные, текущий, будущие. */
export function Stepper({
  steps,
  current,
  label,
  failedAt,
}: {
  steps: string[];
  current: number; // индекс текущего шага; steps.length — все пройдены
  label: string;
  failedAt?: number; // шаг, на котором путь оборвался (например, идея не подтвердилась)
}) {
  return (
    <ol className="stepper" aria-label={label}>
      {steps.map((s, i) => {
        const state = failedAt === i ? "failed" : i < current ? "done" : i === current ? "current" : "todo";
        const word = { failed: "остановлено", done: "пройдено", current: "сейчас", todo: "впереди" }[state];
        return (
          <li key={s} className={`step step-${state}`} aria-current={state === "current" ? "step" : undefined}>
            <span className="step-dot" aria-hidden="true">
              {state === "done" ? "✓" : state === "failed" ? "×" : i + 1}
            </span>
            <span className="step-label">
              {s}
              <span className="sr-only"> — {word}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Путь гипотезы: где она сейчас. */
export function HypothesisPath({ status }: { status: HStatus }) {
  const steps = ["Предложена", "Принята к проверке", "Проверяется", "Проверена"];
  const idx: Record<HStatus, number> = { proposed: 0, accepted: 1, testing: 2, tested: 4, rejected: 1 };
  return (
    <Stepper steps={steps} current={idx[status]} label="Путь идеи" failedAt={status === "rejected" ? 1 : undefined} />
  );
}

/** Подсказка «что дальше» — одна строка с действием. */
export function NextStep({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="next-step" role="note">
      <span className="next-step-label">Что дальше</span>
      <span className="next-step-text">{children}</span>
      {action}
    </div>
  );
}

/** Следующий шаг по эксперименту. Запуск сам статус эксперимента не меняет, поэтому смотрим и на последний расчёт. */
export function experimentNext(status: ExpStatus, runs: RunRow[]): string {
  if (status === "draft" || status === "planned" || status === "running") {
    const last = runs[0]; // расчёты приходят от новых к старым
    if (!last) {
      return status === "draft"
        ? "Черновик: заполните постановку и запустите расчёт на вкладке «Новая проверка»."
        : "Расчёта ещё нет — запустите его на вкладке «Новая проверка».";
    }
    return {
      queued: "Расчёт стоит в очереди — ход виден в разделе «Расчёты» внизу. Отчёт ИИ-помощника появится сам после расчёта.",
      running: "Идёт расчёт — ход виден в разделе «Расчёты» внизу. Отчёт ИИ-помощника появится сам после расчёта.",
      done: "Расчёт завершён: цифры и отчёт ИИ-помощника — на этой странице. Когда отчёт одобрен, переведите проверку в «завершена» через «Редактировать».",
      failed: "Последний расчёт не удался — откройте расчёт внизу, посмотрите лог и запустите снова.",
      stopped: "Последний расчёт остановлен — запустите снова на вкладке «Новая проверка».",
    }[last.status];
  }
  return {
    review: "Результат посчитан и ждёт рецензии: отчёт и рецензии — внизу страницы.",
    done: "Проверка завершена. Если результат меняет методику — по одобренному отчёту предлагается изменение методики.",
    failed: "Расчёт не удался — откройте расчёт внизу, посмотрите лог и перезапустите.",
  }[status];
}

/** Следующий шаг по гипотезе — с учётом роли. */
export function hypothesisNext(status: HStatus, role: string | undefined, code: string, experiment: string): ReactNode {
  switch (status) {
    case "proposed":
      return canReview(role)
        ? "Решите ниже: принять к проверке или отклонить с объяснением."
        : "Ждёт решения рецензента. После принятия ИИ-помощник предложит, как её проверить.";
    case "accepted":
      return canRun(role) ? (
        <>
          Проверьте идею:{" "}
          <Link to={`/run?h=${encodeURIComponent(code)}`}>перейти к новой проверке</Link> — модель предложит метод и данные, или
          задайте их сами.
        </>
      ) : (
        "Ждёт исследователя: он запустит проверку."
      );
    case "testing":
      return experiment ? (
        <>
          Идёт проверка <Link to={`/experiments/${experiment}`} className="mono">{experiment}</Link>. Результат
          и отчёт появятся на его странице.
        </>
      ) : (
        "Идёт проверка."
      );
    case "tested":
      return experiment ? (
        <>
          Проверена — итог в <Link to={`/experiments/${experiment}`} className="mono">{experiment}</Link>. Если результат меняет
          методику, по отчёту можно предложить изменение методики.
        </>
      ) : (
        "Проверена."
      );
    case "rejected":
      return "Отклонена — причина указана ниже. Это нормальный исход.";
  }
}
