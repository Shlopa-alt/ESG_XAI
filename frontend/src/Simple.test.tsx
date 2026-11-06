import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только поведение экранов
const user = (role: string) => ({ id: 1, login: "[логин]", full_name: "", email: "", role, nda_access: false });
const node = (number: string, kind: string, parent: string, title: string, content = "[текст пункта]") => ({
  number, kind, parent, title, content, stability: "draft", position: 0,
});
const TREE = {
  version: "[версия]",
  sections: [
    node("Н1", "direction", "", "[направление]", "[первая фраза направления]. [вторая фраза направления]."),
    node("Н1.В1", "variant", "Н1", "[вариант]"),
    node("Н1.В1.З1", "task", "Н1.В1", "[задание]"),
    node("01", "section", "", "[общее правило]"),
  ],
};
const CR = {
  code: "CR-01", section: "01", action: "edit", new_kind: "", new_title: "", title: "[что меняется]", description: "", status: "proposed",
  proposed_content: "", author: "", source: "", report: "", report_experiment: "", target_version: "", bases: [], reviews: [],
  blockers: [], problems: "", editable: false,
};
const EXP = {
  code: "EXP-001", title: "[проверка с итогом]", hypothesis: "", direction: "", status: "review", outcome: "rejected", data_summary: "",
  conclusion: "[вывод]", methodology_node: "",
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(role: string, routes: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(user(role)));
      const key = Object.keys(routes).find((k) => url.includes(k));
      return Promise.resolve(json(key ? routes[key] : []));
    }),
  );
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

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

Element.prototype.scrollIntoView = vi.fn();

describe("Меню", () => {
  it("«Методика» сразу после «Обзора», служебное только у владельца", async () => {
    stub("reader");
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Разделы платформы" });
    const names = within(nav).getAllByRole("link").map((a) => a.textContent);
    expect(names).toEqual(["Обзор", "Методика", "Банк статей", "Идеи для проверки", "Проверки", "Данные"]);
  });

  it("раздел подсвечен и на его вкладках", async () => {
    stub("researcher");
    renderAt("/runs");
    const nav = await screen.findByRole("navigation", { name: "Разделы платформы" });
    expect(within(nav).getByRole("link", { name: "Проверки" })).toHaveAttribute("aria-current", "page");
  });
});

describe("Обзор", () => {
  it("объясняет ESG и показывает итог проверки, в том числе отрицательный", async () => {
    stub("reader", { "/experiments": [EXP] });
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Что такое ESG" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "[проверка с итогом]" })).toBeInTheDocument();
    expect(screen.getByText("идея не подтвердилась")).toBeInTheDocument();
    expect(screen.getByText("ещё на рецензии")).toBeInTheDocument();
  });

  it("без итогов говорит, что здесь появится", async () => {
    stub("reader");
    renderAt("/");
    expect(await screen.findByText(/Законченных проверок пока нет/)).toBeInTheDocument();
  });

  it("ошибка сервера видна как ошибка", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => Promise.resolve(url.includes("/auth/me") ? json(user("reader")) : json({ detail: "[сбой]" }, 500))),
    );
    renderAt("/");
    expect((await screen.findByRole("alert")).textContent).toContain("Не удалось загрузить результаты");
  });
});

describe("Банк статей и данные", () => {
  it("карта связей и добавление статьи — вкладки одного раздела", async () => {
    stub("reader");
    renderAt("/knowledge");
    const tabs = await screen.findByRole("navigation", { name: "Разделы банка статей" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(["Статьи", "Карта связей", "Добавить статью"]);
  });

  it("наборы данных и данные из статей — вкладки раздела «Данные»", async () => {
    stub("reader", { "/datasets": [] });
    renderAt("/data");
    const tabs = await screen.findByRole("navigation", { name: "Разделы данных" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(["Наборы данных", "Данные из статей"]);
    expect(await screen.findByText("Наборов данных пока нет.")).toBeInTheDocument();
  });

  it("поиск по всем статьям виден только владельцу", async () => {
    stub("researcher");
    renderAt("/data-drafts");
    await screen.findByRole("heading", { name: "Данные из статей" });
    expect(screen.queryByRole("button", { name: /Поискать таблицы/ })).not.toBeInTheDocument();
  });

  it("владелец видит поиск и предупреждение о времени", async () => {
    stub("owner");
    renderAt("/data-drafts");
    expect(await screen.findByRole("button", { name: /Поискать таблицы/ })).toBeInTheDocument();
    expect(screen.getByText(/может занять часы/i)).toBeInTheDocument();
  });
});

describe("Методика", () => {
  const routes = { "/methodology/change-requests": [CR], "/change-requests": [CR], "/methodology": TREE };

  it("пункты свёрнуты: видно название и первую фразу, текст по нажатию", async () => {
    stub("reader", routes);
    renderAt("/methodology");
    const title = await screen.findByText("[направление]");
    const details = title.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText("[первая фраза направления].")).toBeInTheDocument();
    expect(screen.getByText("1 вариант · 1 задание")).toBeInTheDocument();
    await userEvent.click(title);
    expect(details).toHaveAttribute("open");
  });

  it("читателю не предлагают править", async () => {
    stub("reader", routes);
    renderAt("/methodology");
    await screen.findByText("[направление]");
    expect(screen.queryByRole("button", { name: /Предложить правку|Добавить:/ })).not.toBeInTheDocument();
  });

  it("исследователю можно предложить правку", async () => {
    stub("researcher", routes);
    renderAt("/methodology");
    await userEvent.click(await screen.findByText("[общее правило]"));
    expect(screen.getAllByRole("button", { name: "Предложить правку" }).length).toBeGreaterThan(0);
  });

  it("предложения и история — на своих вкладках, число открытых видно сразу", async () => {
    stub("reader", routes);
    renderAt("/methodology");
    const tab = await screen.findByRole("tab", { name: "Предложения изменений · 1" });
    expect(screen.queryByText("[что меняется]")).not.toBeInTheDocument();
    await userEvent.click(tab);
    expect(screen.getByText("[что меняется]")).toBeInTheDocument();
  });

  it("ссылка на предложение из отчёта сразу открывает его вкладку", async () => {
    window.location.hash = "#cr-CR-01";
    stub("reader", routes);
    renderAt("/methodology");
    expect(await screen.findByText("[что меняется]")).toBeInTheDocument();
  });
});
