// Снимки экранов стенда и замеры для рецензентов интерфейса. Параметры — в deploy/review/README.md.
//   --role reader|researcher|reviewer|owner|anon   --routes a,b,c   --widths 1440,390
//   --scenario scenarios/имя.mjs   сценарий из .review: export default async ({ page, shot, step }) => {}
import { mkdirSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { chromium } from "playwright";

const BASE = "http://proxy";
const PASSWORD = "review-stand";
const COMMON = [
  "", "knowledge", "knowledge/graph", "knowledge/import", "hypotheses", "experiments",
  "experiments/EXP-007", "data", "data-drafts", "datasets/DS-01", "run", "runs", "methodology",
];

function option(name, fallback) {
  const at = process.argv.indexOf(`--${name}`);
  return at === -1 ? fallback : process.argv[at + 1];
}

const role = option("role", "researcher");
const widths = option("widths", "1440,390").split(",").map(Number);
const scenario = option("scenario", "");
const defaults = role === "anon" ? [""] : role === "owner" ? [...COMMON, "users", "qwen"] : COMMON;
const routes = option("routes") === undefined ? defaults : option("routes").split(",");

const outDir = `/out/${role}`;
mkdirSync(outDir, { recursive: true });

async function waitForStand(request) {
  for (let i = 0; i < 90; i += 1) {
    try {
      if ((await request.get(`${BASE}/api/auth/me`)).status() < 500) return;
    } catch {
      // стенд ещё поднимается
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("Стенд не ответил за 3 минуты");
}

function watch(page, sink) {
  page.on("console", (m) => {
    if (m.type() === "error") sink.console.push(m.text());
  });
  page.on("pageerror", (e) => sink.console.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 400) sink.http.push(`${r.status()} ${r.url().replace(BASE, "")}`);
  });
}

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
}

async function measure(page) {
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const layout = await page.evaluate(() => {
    const visible = (el) => {
      const box = el.getBoundingClientRect();
      return box.width > 0 && box.height > 0 && getComputedStyle(el).visibility !== "hidden";
    };
    const name = (el) =>
      `${el.tagName.toLowerCase()} «${(el.getAttribute("aria-label") || el.innerText || el.value || "").trim().slice(0, 40)}»`;
    // Вылет страницы не видит таблицу с прокруткой внутри карточки: её столбцы скрыты без подсказки
    const scrollers = [...document.querySelectorAll("body *")]
      .filter((el) => {
        const x = getComputedStyle(el).overflowX;
        return (x === "auto" || x === "scroll") && el.scrollWidth - el.clientWidth > 1 && visible(el);
      })
      .map((el) => ({
        element: `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]}`,
        hidden_px: el.scrollWidth - el.clientWidth,
      }));
    const targets = [...document.querySelectorAll("a, button, input, select, textarea, [role=button]")]
      .filter(visible)
      .map((el) => ({ el, box: el.getBoundingClientRect() }))
      .filter(({ box }) => box.width < 44 || box.height < 44)
      .map(({ el, box }) => `${name(el)} ${Math.round(box.width)}x${Math.round(box.height)}`);
    const smallText = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const parent = walker.currentNode.parentElement;
      const text = walker.currentNode.textContent.trim();
      if (text && parent && visible(parent) && parseFloat(getComputedStyle(parent).fontSize) < 12) {
        smallText.add(`${parseFloat(getComputedStyle(parent).fontSize)}px «${text.slice(0, 40)}»`);
      }
    }
    return {
      horizontal_overflow_px: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      inner_scroll: scrollers,
      targets_under_44px: targets.slice(0, 40),
      text_under_12px: [...smallText].slice(0, 20),
    };
  });
  return {
    ...layout,
    axe: axe.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      count: v.nodes.length,
      examples: v.nodes.slice(0, 3).map((n) => ({
        target: n.target.join(" "),
        detail: n.any[0]?.message ?? n.failureSummary,
      })),
    })),
  };
}

const browser = await chromium.launch();
const context = await browser.newContext({ locale: "ru-RU" });
await waitForStand(context.request);
if (role !== "anon") {
  const login = await context.request.post(`${BASE}/api/auth/login`, {
    data: { login: `review-${role}`, password: PASSWORD },
  });
  if (!login.ok()) throw new Error(`Вход не удался: ${login.status()}`);
}

const report = { role, taken_at: new Date().toISOString(), pages: [], scenarios: [] };

for (const route of routes.filter((r) => r !== "none")) {
  for (const width of widths) {
    const page = await context.newPage();
    await page.setViewportSize({ width, height: 900 });
    const sink = { console: [], http: [] };
    watch(page, sink);
    await page.goto(`${BASE}/${route}`, { waitUntil: "domcontentloaded" });
    await settle(page);
    const slug = (route || "overview").replaceAll("/", "_");
    const file = `${slug}-${width}.png`;
    await page.screenshot({ path: `${outDir}/${file}`, fullPage: true });
    report.pages.push({ route: `/${route}`, width, file, ...(await measure(page)), ...sink });
    await page.close();
  }
}

const scenarioName = scenario ? scenario.split("/").pop().replace(".mjs", "") : "";

// Сценарий идёт на каждой ширине: мобильная форма — такая же часть проверки, как и настольная
for (const width of scenario ? widths : []) {
  const page = await context.newPage();
  await page.setViewportSize({ width, height: 900 });
  const sink = { console: [], http: [] };
  watch(page, sink);
  const steps = [];
  let shots = 0;
  const api = {
    page,
    base: BASE,
    width,
    step: (text) => steps.push(text),
    // fullPage: false — только видимая часть: всплывающая подсказка браузера при снимке всей страницы сдвигает меню
    shot: async (label, { fullPage = true } = {}) => {
      shots += 1;
      await settle(page);
      await page.screenshot({
        path: `${outDir}/${scenarioName}-${width}-${String(shots).padStart(2, "0")}-${label}.png`,
        fullPage,
      });
    },
    // Обход клавишей Tab: что получает фокус и видна ли его обводка
    tabWalk: async (count) => {
      const seen = [];
      for (let i = 0; i < count; i += 1) {
        await page.keyboard.press("Tab");
        seen.push(await page.evaluate(() => {
          const el = document.activeElement;
          const style = getComputedStyle(el);
          return {
            element: `${el.tagName.toLowerCase()} «${(el.getAttribute("aria-label") || el.innerText || el.name || "").trim().slice(0, 40)}»`,
            focus_visible: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0,
          };
        }));
      }
      return seen;
    },
    // Поля формы, не прошедшие проверку: сообщение браузера, aria-invalid, есть ли подпись
    invalidFields: () => page.evaluate(() =>
      [...document.querySelectorAll("input, select, textarea")]
        .filter((el) => !el.validity.valid || el.getAttribute("aria-invalid") === "true")
        .map((el) => ({
          label: el.labels?.[0]?.innerText?.trim().slice(0, 60) ?? "",
          native_message: el.validationMessage,
          aria_invalid: el.getAttribute("aria-invalid"),
        }))),
  };
  let error = null;
  try {
    const module = await import(pathToFileURL(`/out/${scenario}`).href);
    await module.default(api);
  } catch (e) {
    error = String(e);
    await api.shot("error").catch(() => {});
  }
  // Замер там, где сценарий остановился: формы и диалоги с адреса страницы не открыть
  report.scenarios.push({ name: scenarioName, width, steps, error, ...sink, final_state: await measure(page) });
  await page.close();
}

// Прогон сценария не затирает отчёт по страницам и другие сценарии
const reportFile = scenario ? `report-${scenarioName}.json` : "report.json";
writeFileSync(`${outDir}/${reportFile}`, JSON.stringify(report, null, 2));
await browser.close();
console.log(`Готово: .review/${role}/${reportFile}, страниц: ${report.pages.length}, сценариев: ${report.scenarios.length}`);
