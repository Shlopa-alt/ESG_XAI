/** Английская версия интерфейса (п. 3 фидбека): переключатель RU / EN.
 *
 *  Интерфейс написан по-русски прямо в компонентах. Английский — слой поверх: при включённом EN
 *  подписи интерфейса (текст, подсказки, aria-label, placeholder) заменяются по словарю en.ts, в том числе
 *  подписи с числами (шаблоны) и формы «3 статьи». Данные — статьи, понятия, тексты людей, ответы
 *  сервера — не переводятся: их нет в словаре. React при обновлении снова пишет русский текст —
 *  наблюдатель тут же переводит его снова. Язык хранится в браузере; переключение перезагружает страницу.
 *
 *  Словарь собирается из исходников всех страниц (строки с кириллицей); чего в нём нет, остаётся
 *  по-русски. Новые подписи — добавить в en.ts.
 */
import { EN } from "./en";

export type Lang = "ru" | "en";
const KEY = "esg-lang";
const CYR = /[А-Яа-яЁё]/;

export function getLang(): Lang {
  try {
    return localStorage.getItem(KEY) === "en" ? "en" : "ru";
  } catch {
    return "ru";
  }
}

export function setLang(lang: Lang): void {
  try {
    localStorage.setItem(KEY, lang);
  } catch {
    // без хранилища язык не запомнится — останется русский
  }
  window.location.reload();
}

const norm = (s: string) => s.trim().replace(/\s+/g, " ");
const exact = new Map(Object.entries(EN.exact).map(([ru, en]) => [norm(ru), en]));
const lower = new Map([...exact].map(([ru, en]) => [ru.toLowerCase(), en]));
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const templates = Object.entries(EN.templates)
  .map(([ru, en]) => ({
    literal: ru.replace(/\{\d+\}/g, "").length,
    // «{0} в {1}», «{0} с»: постоянного текста почти нет — такой шаблон годится, только если
    // подставленные части тоже перевелись (иначе он «переводит» данные: «сети в библиотеке» → «сети in…»)
    loose: (ru.replace(/\{\d+\}/g, "").match(/[А-Яа-яЁё]/g) ?? []).length < 4,
    re: new RegExp(`^${escape(norm(ru)).replace(/\\\{(\d+)\\\}/g, "([\\s\\S]*?)")}$`),
    en,
  }))
  .sort((a, b) => b.literal - a.literal); // где больше постоянного текста — точнее
const forms = new Map<string, [string, string]>();
for (const [ru, en] of Object.entries(EN.plural)) for (const f of ru.split("|")) forms.set(f, en);

function caseLike(src: string, out: string): string {
  if (src === src.toUpperCase() && src !== src.toLowerCase()) return out.toUpperCase();
  const first = src.charAt(0);
  if (first && first === first.toUpperCase() && first !== first.toLowerCase()) return out.charAt(0).toUpperCase() + out.slice(1);
  return out;
}

function plural(key: string): string | undefined {
  const m = /^(-?[\d\s\u00a0\u202f]*[\d][\d.,]*)\s+(.+)$/.exec(key);
  if (!m?.[1] || !m[2]) return undefined;
  const f = forms.get(m[2]);
  if (!f) return undefined;
  const n = Number(m[1].replace(/[\s\u00a0\u202f]/g, "").replace(",", "."));
  return `${m[1]} ${n === 1 ? f[0] : f[1]}`;
}

/** Строка интерфейса по-английски; чего нет в словаре — как было. */
export function translate(s: string, depth = 0): string {
  if (!CYR.test(s) || depth > 3) return s;
  const key = norm(s);
  let out = exact.get(key) ?? plural(key);
  if (out === undefined) {
    const k = lower.get(key.toLowerCase());
    if (k !== undefined) out = caseLike(key, k);
  }
  if (out === undefined) {
    for (const t of templates) {
      const m = t.re.exec(key);
      if (m) {
        const got = t.en.replace(/\{(\d+)\}/g, (_, i: string) => translate(m[Number(i) + 1] ?? "", depth + 1));
        if (t.loose && CYR.test(got)) continue;
        out = got;
        break;
      }
    }
  }
  if (out === undefined && key.includes(" · ")) {
    // «1 вариант · 1 задание», «EXP-901 · задание методики не указано» — по частям, если перевелись все
    const parts = key.split(" · ").map((p) => translate(p, depth + 1));
    if (!parts.some((p) => CYR.test(p))) out = parts.join(" · ");
  }
  if (out === undefined) return s;
  const lead = /^\s*/.exec(s)?.[0] ?? "";
  const trail = /\s*$/.exec(s)?.[0] ?? "";
  return lead + out + trail;
}

const ATTRS = ["placeholder", "title", "aria-label", "alt"];
// не трогаем то, что человек вводит, код и помеченное «не переводить»; в <pre> — только однострочное
// (сообщение «лога нет»), многострочное там — команды и лог
const SKIP = "textarea, input, [contenteditable], code, [translate='no'], .notranslate";

function fixText(n: Node): void {
  const v = n.nodeValue;
  if (!v || !CYR.test(v) || n.parentElement?.closest(SKIP)) return;
  if (v.trim().includes("\n") && n.parentElement?.closest("pre")) return;
  const t = translate(v);
  if (t !== v) n.nodeValue = t;
}

function fixAttrs(el: Element): void {
  if (el.closest("[translate='no'], .notranslate")) return;
  for (const a of ATTRS) {
    const v = el.getAttribute(a);
    if (v && CYR.test(v)) {
      const t = translate(v);
      if (t !== v) el.setAttribute(a, t);
    }
  }
}

function walk(node: Node): void {
  if (node.nodeType === Node.TEXT_NODE) {
    fixText(node);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const el = node as Element;
  fixAttrs(el);
  const it = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let n = it.nextNode(); n; n = it.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) fixText(n);
    else fixAttrs(n as Element);
  }
}

/** Включить английский: перевести то, что уже на странице, и всё, что появится. */
export function startTranslator(root: HTMLElement): MutationObserver {
  document.documentElement.lang = "en";
  walk(root);
  const title = () => {
    const t = translate(document.title);
    if (t !== document.title) document.title = t;
  };
  title();
  const obs = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === "characterData") fixText(m.target);
      else if (m.type === "attributes") fixAttrs(m.target as Element);
      else m.addedNodes.forEach(walk);
    }
    title();
  });
  obs.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  return obs;
}
