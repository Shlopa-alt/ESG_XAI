import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type Draft, LANG_TITLE, translateDraft } from "../api/dataDrafts";

export type View = "ru" | "orig";

/** Как показывать строку: по-русски, если есть перевод и выбран русский вид. */
export function translator(d: Draft, view: View): (s: string) => string {
  const pairs = d.translation?.pairs ?? {};
  return (s: string) => (view === "ru" ? (pairs[s.trim()] ?? s) : s);
}

/** Перевод черновика из иностранной статьи (п. 6 фидбека): переключатель «По-русски / Оригинал»,
 *  что и чем переведено, перевод в очереди — и кнопка перевести (заново) с выбором языка. */
export function TranslationBar({
  d,
  view,
  setView,
  canTranslate,
}: {
  d: Draft;
  view: View;
  setView: (v: View) => void;
  canTranslate: boolean;
}) {
  const qc = useQueryClient();
  const [lang, setLang] = useState("");
  const t = d.translation;
  const go = useMutation({
    mutationFn: () => translateDraft(d.id, lang),
    onSuccess: (data) => qc.setQueryData(["data-draft", d.id], data),
  });
  if (!t) return null;
  const has = Object.keys(t.pairs).length > 0;
  // русская таблица или одни числа — и перевода не было: показывать нечего. Язык не определился или
  // переводчик его не знает, а иностранные строки есть — блок нужен: язык выбирают вручную
  if (!has && !t.has_texts && !t.pending && !t.failed) return null;
  const from = LANG_TITLE[t.source] ?? t.lang_title;
  return (
    <section className="card translate-bar" aria-labelledby="tr-title">
      <h2 className="h3" id="tr-title">
        Перевод на русский
      </h2>
      {has && (
        <div className="filters" role="group" aria-label="Язык таблицы">
          <button type="button" className={view === "ru" ? "chip active" : "chip"} aria-pressed={view === "ru"} onClick={() => setView("ru")}>
            По-русски
          </button>
          <button
            type="button"
            className={view === "orig" ? "chip active" : "chip"}
            aria-pressed={view === "orig"}
            onClick={() => setView("orig")}
          >
            Оригинал{from ? ` (${from})` : ""}
          </button>
        </div>
      )}
      {has && (
        <p className="muted">
          Переведено машинно{from ? ` с языка: ${from}` : ""}
          {t.engine ? ` (${t.engine})` : ""}. Числа не переводятся. Проверяйте важное по оригиналу: в набор данных уходит
          оригинал таблицы.
        </p>
      )}
      {!has && !t.pending && t.lang_title && t.supported && (
        <p className="muted">Таблица на языке: {t.lang_title}. Перевода пока нет.</p>
      )}
      {!has && !t.pending && t.lang_title && !t.supported && (
        <p className="muted">
          Таблица на языке: {t.lang_title}. Этот язык переводчик пока не знает, поэтому таблица не переводится сама. Если язык
          определён неверно, выберите его ниже.
        </p>
      )}
      {!has && !t.pending && !t.lang_title && t.has_texts && (
        <p className="muted">Язык таблицы не определился сам. Выберите язык оригинала и нажмите «Перевести на русский».</p>
      )}
      {t.pending && (
        <p role="status">
          {t.pending === "running" ? "Переводится…" : "Перевод в очереди…"}
          {t.translator_online === false && (
            <span className="muted">
              {" "}
              Переводчик на лабораторном ПК сейчас не запущен — перевод начнётся, когда его включат.
            </span>
          )}
        </p>
      )}
      {t.failed && !t.pending && (
        <p className="error" role="alert">
          Перевод не удался: {t.failed}
        </p>
      )}
      {canTranslate && !t.pending && (
        <div className="review-form">
          <label className="field">
            Язык оригинала
            <select value={lang} onChange={(e) => setLang(e.target.value)}>
              <option value="">
                {!t.lang_title ? "— выберите —" : t.supported ? `определён: ${t.lang_title}` : `определён: ${t.lang_title} (не переводится)`}
              </option>
              {Object.entries(LANG_TITLE).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn-ghost" disabled={go.isPending || (!t.can_translate && !lang)} onClick={() => go.mutate()}>
            {go.isPending ? "Ставлю в очередь…" : has ? "Перевести заново" : "Перевести на русский"}
          </button>
        </div>
      )}
      {go.isError && (
        <p className="error" role="alert">
          {go.error.message}
        </p>
      )}
    </section>
  );
}
