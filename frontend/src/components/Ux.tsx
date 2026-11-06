import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { HStatus } from "../api/hypotheses";
import type { ExpStatus } from "../api/experiments";
import type { RunRow } from "../pages/RunPage";

/** Человеческое название роли и что ей можно — чтобы было понятно, почему не видно кнопок. */
export const ROLE_LABEL: Record<string, { name: string; can: string }> = {
  reader: { name: "читатель", can: "смотреть материалы (файлы под NDA — только с допуском) и предлагать гипотезы" },
  researcher: { name: "исследователь", can: "предлагать гипотезы, создавать и запускать эксперименты" },
  reviewer: { name: "рецензент", can: "принимать и отклонять гипотезы, рецензировать эксперименты и CR" },
  owner: { name: "руководитель", can: "всё, включая принятие изменений методологии и доступы" },
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

/** Шаги исследовательского цикла — одни и те же на обзоре и в меню. */
export const CYCLE = [
  { n: 1, title: "База знаний", text: "Статьи и факты с цитатами", to: "/knowledge" },
  { n: 2, title: "Гипотеза", text: "Что проверить — от человека или Qwen", to: "/hypotheses" },
  { n: 3, title: "Эксперимент", text: "Расчёт на данных и отчёт", to: "/run" },
  { n: 4, title: "Методология", text: "Изменение по итогам (CR)", to: "/methodology" },
] as const;

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
  failedAt?: number; // шаг, на котором путь оборвался (например, гипотеза отклонена)
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
    <Stepper steps={steps} current={idx[status]} label="Путь гипотезы" failedAt={status === "rejected" ? 1 : undefined} />
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
    const last = runs[0]; // запуски приходят от новых к старым
    if (!last) {
      return status === "draft"
        ? "Черновик: заполните постановку и запустите расчёт на странице «Запуск экспериментов»."
        : "Расчёта ещё нет — запустите его на странице «Запуск экспериментов».";
    }
    return {
      queued: "Расчёт стоит в очереди — ход виден в разделе «Запуски» внизу. Отчёт Qwen появится сам после расчёта.",
      running: "Идёт расчёт — ход виден в разделе «Запуски» внизу. Отчёт Qwen появится сам после расчёта.",
      done: "Расчёт завершён: цифры и отчёт Qwen — на этой странице. Когда отчёт одобрен, переведите эксперимент в «завершён» через «Редактировать».",
      failed: "Последний расчёт не удался — откройте запуск внизу, посмотрите лог и запустите снова.",
      stopped: "Последний расчёт остановлен — запустите снова на странице «Запуск экспериментов».",
    }[last.status];
  }
  return {
    review: "Результат посчитан и ждёт рецензии: отчёт и рецензии — внизу страницы.",
    done: "Эксперимент завершён. Если результат меняет методику — по одобренному отчёту предлагается изменение (CR).",
    failed: "Расчёт не удался — откройте запуск внизу, посмотрите лог и перезапустите.",
  }[status];
}

/** Следующий шаг по гипотезе — с учётом роли. */
export function hypothesisNext(status: HStatus, role: string | undefined, code: string, experiment: string): ReactNode {
  switch (status) {
    case "proposed":
      return canReview(role)
        ? "Решите ниже: принять к проверке или отклонить с объяснением."
        : "Ждёт решения рецензента. После принятия Qwen предложит, как её проверить.";
    case "accepted":
      return canRun(role) ? (
        <>
          Проверьте гипотезу экспериментом:{" "}
          <Link to={`/run?h=${encodeURIComponent(code)}`}>перейти к запуску</Link> — модель предложит метод и данные, или
          задайте их сами.
        </>
      ) : (
        "Ждёт исследователя: он запустит проверочный эксперимент."
      );
    case "testing":
      return experiment ? (
        <>
          Идёт проверка в эксперименте <Link to={`/experiments/${experiment}`} className="mono">{experiment}</Link>. Результат
          и отчёт появятся на его странице.
        </>
      ) : (
        "Идёт проверка экспериментом."
      );
    case "tested":
      return experiment ? (
        <>
          Проверена — итог в <Link to={`/experiments/${experiment}`} className="mono">{experiment}</Link>. Если результат меняет
          методику, по отчёту можно предложить изменение (CR).
        </>
      ) : (
        "Проверена."
      );
    case "rejected":
      return "Отклонена — причина указана ниже. Это нормальный исход.";
  }
}
