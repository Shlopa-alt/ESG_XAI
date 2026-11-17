import { getLang, setLang } from "../i18n";

/** Переключатель языка интерфейса RU / EN (п. 3 фидбека). Подпись не переводится: она про сам язык. */
export function LangSwitch() {
  const lang = getLang();
  const next = lang === "ru" ? "en" : "ru";
  return (
    <button
      type="button"
      className="btn-ghost lang-switch"
      translate="no"
      lang={next}
      aria-label={next === "en" ? "Switch to English" : "Переключить на русский"}
      title={next === "en" ? "Switch to English" : "Переключить на русский"}
      onClick={() => setLang(next)}
    >
      {next === "en" ? "EN" : "RU"}
    </button>
  );
}
