import type { LinkMethod, LinksOut } from "../api/analysis";

/** Способы поиска связей (п. 8 фидбека): что делает каждый, когда подходит и чего не видит.
 *  Сам расчёт — runner/methods/correlation_scan.py (METHODS). */
export const LINK_METHODS: Array<{
  key: LinkMethod;
  title: string;
  stat: string;
  how: string;
  good: string;
  blind: string;
}> = [
  {
    key: "rank",
    title: "Любые связи",
    stat: "ρ Спирмена и ξ Чаттерджи",
    how:
      "Смотрит на порядок значений: растёт ли один показатель, когда растёт другой, — и зависит ли один от " +
      "другого хоть как-то, даже если связь U-образная или пороговая.",
    good: "Когда не знаете, чего ждать. Не боится выбросов и разных единиц измерения.",
    blind: "Не отличает прямую связь от связи через третий показатель.",
  },
  {
    key: "linear",
    title: "Только прямолинейные",
    stat: "r Пирсона",
    how: "Обычная корреляция: насколько точки ложатся на прямую «больше одного — больше (или меньше) другого».",
    good: "Когда нужна привычная корреляция — для статьи или сравнения с литературой.",
    blind: "U-образных и пороговых связей не видит; один выброс может и создать связь, и скрыть её.",
  },
  {
    key: "partial",
    title: "Без влияния остальных показателей",
    stat: "частная ρ",
    how:
      "Сначала убирает из обоих показателей то, что объясняют остальные столбцы набора, и только потом ищет " +
      "связь. Если доход и выбросы связаны лишь потому, что оба растут с размером компании, связь пропадёт.",
    good: "Когда подозреваете, что за связью стоит третий показатель: размер, отрасль, год.",
    blind:
      "Нужны строки без пропусков и строк заметно больше, чем столбцов; учитывает только показатели из набора, " +
      "а не всё на свете.",
  },
];

export const methodTitle = (m: string | undefined) => LINK_METHODS.find((x) => x.key === (m || "rank"))?.title ?? m ?? "";

/** Выбор способа: карточки-переключатели; у каждой — сколько связей уже нашёл этот способ. */
export function MethodPicker({
  value,
  onChange,
  scans,
}: {
  value: LinkMethod;
  onChange: (m: LinkMethod) => void;
  scans: LinksOut["scans"];
}) {
  return (
    <fieldset className="method-picker">
      <legend>Каким способом искать связи</legend>
      {LINK_METHODS.map((m) => {
        const s = scans?.find((x) => x.method === m.key);
        const id = `link-method-${m.key}`;
        return (
          <label key={m.key} htmlFor={id} className={value === m.key ? "method-option selected" : "method-option"}>
            <input id={id} type="radio" name="link-method" checked={value === m.key} onChange={() => onChange(m.key)} />
            <span className="method-option-body">
              <strong>{m.title}</strong> <span className="muted">· {m.stat}</span>
              {s && (
                <span className="badge st-review method-found">
                  {s.status === "done"
                    ? `нашёл: ${s.confirmed ?? 0}`
                    : s.status === "queued" || s.status === "running"
                      ? "ищет…"
                      : "не закончился"}
                </span>
              )}
              <span className="method-line">{m.how}</span>
              <span className="method-line">
                <span className="method-tag ok">Подходит</span> {m.good}
              </span>
              <span className="method-line">
                <span className="method-tag warn">Не видит</span> {m.blind}
              </span>
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

/** Общее для всех способов: как поиск отличает связь от случайности. */
export function HowSearchWorks() {
  return (
    <details className="how-search">
      <summary>Как поиск отличает связь от случайности — одинаково для всех способов</summary>
      <ol className="list">
        <li>Данные делятся случайно на две части: на одной ищем, на другой проверяем.</li>
        <li>
          На первой части проверяются все пары показателей. Пар бывают сотни, и случайные «находки» среди них
          неизбежны — поправка на множественное сравнение отсекает их: ложных находок допускается не больше 10 %.
        </li>
        <li>Каждая находка перепроверяется на второй части, которую поиск не видел. Подтвердилась — кандидат в идею.</li>
        <li>
          Контроль: поиск повторяется на перемешанных данных, где связей нет по построению, — видно, сколько ложных
          находок даёт сам поиск.
        </li>
        <li>У панели (компания × год) строки сначала усредняются по компании: одна компания — одно наблюдение.</li>
        <li>Номера и коды строк (code, ИНН, тикер) и годы — не показатели: в поиск не идут.</li>
      </ol>
      <p className="muted">Связь — не причина: она говорит, что показатели меняются вместе, но не что из чего следует.</p>
    </details>
  );
}
