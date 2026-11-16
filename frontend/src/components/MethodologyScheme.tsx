import { Link } from "react-router-dom";

import type { Section } from "../api/methodology";

/** Числа для схемы — из тех же запросов, что уже делает страница методики. */
export interface SchemeCounts {
  ideas: number;
  checks: number;
  checksWithResult: number;
  crOpen: number;
  crAccepted: number;
  versions: number;
  version: string | null;
}

type PageTab = "changes" | "history";

interface Step {
  to?: string; // другая страница
  tab?: PageTab; // вкладка этой же страницы
  title: string;
  text: string;
  n: number | null;
}

const svg = { "aria-hidden": true, focusable: false } as const;

/** Схема методики (п. 7 фидбека): из чего она состоит и как меняется. Смысл дублирован текстом. */
export function MethodologyScheme({
  nodes,
  counts,
  openTab,
}: {
  nodes: Section[];
  counts: SchemeCounts;
  /** «Предложение» и «Новая версия» — вкладки этой же страницы */
  openTab: (tab: PageTab) => void;
}) {
  const count = (kind: Section["kind"]) => nodes.filter((n) => n.kind === kind).length;
  const structure = [
    { kind: "direction", title: "Направление", text: "Большой вопрос лаборатории", n: count("direction") },
    { kind: "variant", title: "Вариант", text: "Один из подходов к нему", n: count("variant") },
    { kind: "task", title: "Задание", text: "Что именно считаем: входы, результат, горизонт", n: count("task") },
  ];
  const cycle: Step[] = [
    { to: "/knowledge", title: "Статья", text: "В банке статей нашлось утверждение с цитатой", n: null },
    { to: "/hypotheses", title: "Идея", text: "Его формулируют как идею для проверки", n: counts.ideas },
    { to: "/experiments", title: "Проверка", text: "Идею считают на данных — расчёт и отчёт", n: counts.checks },
    {
      to: "/experiments",
      title: "Рецензия",
      text: "Другой человек смотрит итог; «не подтвердилось» — тоже итог",
      n: counts.checksWithResult,
    },
    { tab: "changes", title: "Предложение", text: "Изменить пункт можно только с основанием", n: counts.crOpen },
    { tab: "history", title: "Новая версия", text: "Решают люди; принятое меняет методику", n: counts.versions },
  ];
  return (
    <section className="card scheme" aria-labelledby="scheme-title">
      <h2 className="h2" id="scheme-title">
        Как устроена методика
      </h2>
      <div className="scheme-grid">
        <div>
          <h3 className="h3">Из чего она состоит</h3>
          <ol className="scheme-tree">
            {structure.map((s, i) => (
              <li key={s.kind} className={`scheme-level level-${i}`}>
                <span className="scheme-box">
                  <strong>{s.title}</strong>
                  <span className="muted">{s.text}</span>
                  <span className="scheme-n" aria-label={`сейчас: ${s.n}`}>
                    {s.n}
                  </span>
                </span>
              </li>
            ))}
          </ol>
          <p className="muted scheme-note">
            <span className="scheme-rule" aria-hidden="true" /> Правила (разделы) можно прикрепить к любому пункту — они
            действуют на всё, что ниже. Сейчас правил: {count("section")}.
          </p>
        </div>
        <div>
          <h3 className="h3">Как она меняется</h3>
          <ol className="scheme-cycle">
            {cycle.map((s, i) => (
              <li key={s.title} className="scheme-step">
                {s.tab ? (
                  <button type="button" className="scheme-box" onClick={() => s.tab && openTab(s.tab)}>
                    <StepBody i={i} step={s} />
                  </button>
                ) : (
                  <Link to={s.to ?? "/"} className="scheme-box">
                    <StepBody i={i} step={s} />
                  </Link>
                )}
                {i < cycle.length - 1 && (
                  <svg {...svg} className="scheme-arrow" viewBox="0 0 24 24">
                    <path d="M4 12h14m-5-5 5 5-5 5" />
                  </svg>
                )}
              </li>
            ))}
          </ol>
          <p className="muted scheme-note">
            <svg {...svg} className="scheme-loop" viewBox="0 0 24 24">
              <path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" />
            </svg>{" "}
            Круг замыкается: новая версия{counts.version ? ` (сейчас ${counts.version})` : ""} даёт новые вопросы к
            статьям и данным. Принято изменений: {counts.crAccepted}.
          </p>
        </div>
      </div>
    </section>
  );
}

function StepBody({ i, step }: { i: number; step: Step }) {
  return (
    <>
      <span className="scheme-num" aria-hidden="true">
        {i + 1}
      </span>
      <strong>{step.title}</strong>
      <span className="muted">{step.text}</span>
      {step.n !== null && <span className="scheme-n">{step.n}</span>}
    </>
  );
}
