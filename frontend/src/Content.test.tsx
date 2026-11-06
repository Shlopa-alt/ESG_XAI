import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только поведение экранов
const user = (role: string) => ({ id: 1, login: "[логин]", full_name: "", email: "", role, nda_access: false });
const STATS = { kb: "esg", kb_title: "[банк]", documents: 5861, chunks: 205978, facts: 88197, year_from: 2018, year_to: 2026 };
const TREE = {
  current: "esg",
  title: "[банк]",
  examples: [],
  nodes: [
    { path: "esg", title: "[все]", depth: 0, own: 0, subtree: 5861, in_db: true },
    { path: "esg.ratings", title: "[тема рейтинги]", depth: 1, own: 130, subtree: 130, in_db: true },
  ],
};
const entity = (name: string, facts = 10) => ({ id: `e:${name}`, kind: "сущность", name, facts, spellings: [] as string[] });
const fact = (a: string, label: string, b: string, weight = 3) => ({ source: `e:${a}`, target: `e:${b}`, label, type: "факт", weight });
const NETWORK = {
  nodes: [entity("esg performance", 90), entity("firm value", 80), entity("roa", 70), entity("[редкое понятие]", 2), entity("corporate governance", 60)],
  edges: [
    fact("esg performance", "повышает", "firm value", 12),
    fact("corporate governance", "влияет на", "esg performance", 5),
    fact("esg performance", "снижает", "roa", 2),
    fact("firm value", "связано с", "[редкое понятие]", 1),
  ],
};
const DATASET = {
  name: "esg performance",
  facts: [
    { about: "esg performance", direction: "→", relation: "повышает", other: "firm value", quotes: [{ quote: "[цитата из статьи]", doc_id: "d1", title: "[статья]", year: 2024, url: null }] },
  ],
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(role: string, routes: Record<string, unknown> = {}) {
  const urls: string[] = [];
  const all: Record<string, unknown> = {
    "/kb/stats": STATS,
    "/kb/kbs": TREE,
    "/kb/network": NETWORK,
    "/kb/dataset": DATASET,
    ...routes,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      urls.push(url);
      if (url.includes("/auth/me")) return Promise.resolve(json(user(role)));
      const key = Object.keys(all).find((k) => url.includes(k));
      return Promise.resolve(json(key ? all[key] : []));
    }),
  );
  return urls;
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Шапка меню", () => {
  it("показывает сотрудничество с лабораторией и понятную роль", async () => {
    stub("owner");
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Разделы платформы" });
    expect(within(nav).getByText(/совместно с Лабораторией/)).toBeInTheDocument();
    expect(within(nav).getByText(/администратор/)).toBeInTheDocument();
    expect(within(nav).queryByText(/руководитель/)).not.toBeInTheDocument();
  });
});

describe("Обзор", () => {
  it("показывает, сколько всего уже есть, и ведёт в разделы", async () => {
    stub("reader", { "/hypotheses": [{ code: "H-1", status: "proposed" }, { code: "H-2", status: "testing" }], "/datasets": [{ code: "DS-01", title: "", description: "", source_url: "", access_level: "public", snapshots: 1 }, { code: "DS-02", title: "", description: "", source_url: "", access_level: "public", snapshots: 0 }] });
    renderAt("/");
    const tiles = await screen.findByRole("region", { name: "Что уже есть на платформе" });
    expect(await within(tiles).findByRole("link", { name: /5\s861 статья в банке/ })).toHaveAttribute("href", "/knowledge");
    expect(within(tiles).getByRole("link", { name: /88\s197 утверждений с цитатами/ })).toHaveAttribute("href", "/knowledge/graph");
    expect(await within(tiles).findByRole("link", { name: /2 идеи для проверки.*ждут решения: 1/ })).toBeInTheDocument();
    expect(await within(tiles).findByRole("link", { name: /2 набора данных.*с файлами: 1/ })).toBeInTheDocument();
  });

  it("объясняет, что изучаем, как работаем и почему можно доверять", async () => {
    stub("reader");
    renderAt("/");
    for (const name of ["Что такое ESG", "Что мы изучаем", "Как мы работаем", "Почему этому можно доверять", "Основные слова", "С чего начать"]) {
      expect(await screen.findByRole("heading", { name })).toBeInTheDocument();
    }
  });
});

describe("Банк статей", () => {
  const docs = (n: number, total: number) => ({ total, documents: Array.from({ length: n }, (_, i) => ({ doc_id: `d${i}`, title: `[статья ${i}]`, year: 2024, chunks: 1 })) });

  it("показывает настоящее число статей, а не обрезанный список", async () => {
    stub("reader", { "/kb/documents": docs(25, 5861) });
    renderAt("/knowledge");
    expect(await screen.findByRole("heading", { name: /Все статьи · 5\s861/ })).toBeInTheDocument();
    expect(screen.getByText(/Показано 25 из 5\s861/)).toBeInTheDocument();
    expect(screen.queryByText(/Что ещё будет/)).not.toBeInTheDocument();
  });

  it("«Показать ещё» запрашивает следующие статьи", async () => {
    const urls = stub("reader", { "/kb/documents": docs(25, 5861) });
    renderAt("/knowledge");
    await userEvent.click(await screen.findByRole("button", { name: "Показать ещё 25" }));
    expect(urls.some((u) => u.includes("/kb/documents") && u.includes("limit=50"))).toBe(true);
  });

  it("темы показаны с числом статей и фильтруют список", async () => {
    const urls = stub("reader", { "/kb/documents": docs(1, 1) });
    renderAt("/knowledge");
    await userEvent.click(await screen.findByRole("button", { name: "[тема рейтинги] · 130" }));
    expect(urls.some((u) => u.includes("/kb/documents") && u.includes("kb=esg.ratings"))).toBe(true);
  });

  it("поиск по названию уходит на сервер", async () => {
    const urls = stub("reader", { "/kb/documents": docs(1, 1) });
    renderAt("/knowledge");
    await userEvent.type(await screen.findByLabelText("Найти статью по названию"), "rating");
    await userEvent.keyboard("{Enter}");
    expect(urls.some((u) => u.includes("/kb/documents") && u.includes("q=rating"))).toBe(true);
  });
});

describe("Карта связей", () => {
  it("открывает понятное понятие: что влияет слева, на что влияет справа, по-русски", async () => {
    stub("reader");
    renderAt("/knowledge/graph");
    expect(await screen.findByRole("heading", { name: "ESG-показатели" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Что на это влияет" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Корпоративное управление\s*corporate governance/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Стоимость компании\s*firm value/ })).toBeInTheDocument();
  });

  it("нажатие на соседа открывает его, а «Назад» возвращает", async () => {
    stub("reader");
    renderAt("/knowledge/graph");
    await userEvent.click(await screen.findByRole("button", { name: /^Стоимость компании\s*firm value$/ }));
    expect(await screen.findByRole("heading", { name: "Стоимость компании" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "← Назад: ESG-показатели" }));
    expect(await screen.findByRole("heading", { name: "ESG-показатели" })).toBeInTheDocument();
  });

  it("число статей открывает цитаты по этой связи", async () => {
    stub("reader");
    renderAt("/knowledge/graph");
    await userEvent.click(await screen.findByRole("button", { name: /повышает\s*12 статей/ }));
    expect(await screen.findByText(/\[цитата из статьи\]/)).toBeInTheDocument();
  });

  it("находит понятие и по-русски", async () => {
    stub("reader");
    renderAt("/knowledge/graph");
    await userEvent.type(await screen.findByLabelText("Найти понятие на карте"), "рентабельность активов");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "Рентабельность активов (ROA)" })).toBeInTheDocument();
  });

  it("если ничего не найдено, говорит об этом", async () => {
    stub("reader");
    renderAt("/knowledge/graph");
    await userEvent.type(await screen.findByLabelText("Найти понятие на карте"), "нет такого");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText(/Такого понятия нет/)).toBeInTheDocument();
  });

  it("фильтр связей убирает лишние строки", async () => {
    stub("reader");
    renderAt("/knowledge/graph");
    await screen.findByRole("button", { name: /Стоимость компании\s*firm value/ });
    await userEvent.click(screen.getByRole("button", { name: "повышает" }));
    expect(screen.queryByRole("button", { name: /повышает\s*12 статей/ })).not.toBeInTheDocument();
  });
});

describe("Карта связей: большие списки", () => {
  it("при равном числе статей выше понятие, о котором пишут чаще, а список раскрывается порциями", async () => {
    const many = Array.from({ length: 40 }, (_, i) => entity(`[сосед ${i}]`, i));
    stub("reader", {
      "/kb/network": {
        nodes: [entity("esg performance", 90), ...many],
        edges: many.map((n) => fact("esg performance", "влияет на", n.name ?? "", 1)),
      },
    });
    renderAt("/knowledge/graph");
    const more = await screen.findByRole("button", { name: "Показать ещё 20 из 32" });
    const rows = screen.getAllByRole("button", { name: /^\[сосед/ });
    expect(rows[0]).toHaveTextContent("[сосед 39]");
    expect(rows).toHaveLength(8);
    await userEvent.click(more);
    expect(screen.getAllByRole("button", { name: /^\[сосед/ })).toHaveLength(28);
  });

  it("русское понятие из базы показано с заглавной буквы", async () => {
    stub("reader", { "/kb/network": { nodes: [entity("стоимость капитала", 5)], edges: [] } });
    renderAt("/knowledge/graph");
    expect(await screen.findByText(/В этой теме связей пока нет/)).toBeInTheDocument();
  });
});

describe("Данные", () => {
  it("показывает, у каких наборов есть файлы, и ведёт к данным из статей", async () => {
    stub("reader", { "/datasets": [{ code: "DS-01", title: "[с файлами]", description: "", source_url: "", access_level: "public", snapshots: 2 }, { code: "DS-02", title: "[без файлов]", description: "", source_url: "", access_level: "public", snapshots: 0 }] });
    renderAt("/data");
    expect(await screen.findByText("2 версии")).toBeInTheDocument();
    expect(screen.getByText("пока нет")).toBeInTheDocument();
    expect(screen.getByText(/с загруженными файлами: 1/)).toBeInTheDocument();
  });
});
