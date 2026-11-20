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
    expect(names).toEqual([
      "Обзор", "Методика", "Банк статей", "Идеи для проверки", "Проверки", "Нейросети", "Данные", "Доступ к API",
    ]);
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

  it("начинается с цели: проверить методику, с её версией и спорными пунктами", async () => {
    const node = (number: string, stability: string) => ({ number, title: "[пункт]", content: "", stability, kind: "section", parent: "", position: 0 });
    stub("reader", { "/methodology": { version: "[версия]", sections: [node("1", "stable"), node("2", "draft"), node("3", "contested")] } });
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Наша цель — проверить методику лаборатории" })).toBeInTheDocument();
    expect(await screen.findByText("Методика, версия [версия]")).toBeInTheDocument();
    expect(screen.getByText("3 пункта · черновиков: 1 · оспаривается: 1")).toBeInTheDocument();
    const outcomes = screen.getByRole("list", { name: "Что проверка может дать методике" });
    expect(within(outcomes).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Открыть методику" })).toHaveAttribute("href", "/methodology");
  });

  it("показывает, как менялась методика: версии от первой к последней, принятые изменения — в плитке", async () => {
    stub("reader", {
      "/methodology/versions": [
        { version: "[в2]", notes: "[CR-2]: [второе изменение]", created_at: "2026-02-01T00:00:00Z", points: 6, rules: 2 },
        { version: "[в1]", notes: "[CR-1]: [первое изменение]", created_at: "2026-01-01T00:00:00Z", points: 4, rules: 1 },
      ],
      "/change-requests": [{ ...CR, status: "accepted" }],
    });
    renderAt("/");
    const list = await screen.findByRole("list", { name: "Версии методики" });
    expect(within(list).getAllByRole("listitem").map((li) => li.querySelector(".mono")?.textContent)).toEqual(["[в1]", "[в2]"]);
    expect(within(list).getByText(/6 пунктов \(\+2\)/)).toBeInTheDocument();
    // путь «статьи → изменения» — в плитках: принятые изменения методики и открытые предложения
    const tiles = screen.getByRole("region", { name: "Что уже есть на платформе" });
    expect(await within(tiles).findByRole("link", { name: /1 изменение методики принято.*открытых предложений: 0/ })).toHaveAttribute("href", "/methodology");
  });

  it("без версий методики говорит, когда появится первая", async () => {
    stub("reader");
    renderAt("/");
    expect(await screen.findByText(/Версий методики пока нет/)).toBeInTheDocument();
  });

  it("без опубликованной методики цель всё равно объяснена", async () => {
    stub("reader");
    renderAt("/");
    expect(await screen.findByText("Пункты методики появятся здесь, когда её опубликуют")).toBeInTheDocument();
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

  it("у пункта — переход «Что говорят статьи» сразу на этот пункт", async () => {
    stub("reader", routes);
    renderAt("/methodology");
    await userEvent.click(await screen.findByText("[направление]"));
    await userEvent.click(screen.getAllByRole("button", { name: "Что говорят статьи" })[0] as HTMLElement);
    expect(screen.getByRole("tab", { name: "Что говорят статьи" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Пункт методики")).toHaveValue("Н1");
    expect(window.location.hash).toBe("#articles-%D0%9D1");
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

  it("«Что говорят статьи»: понятия пункта, сводка с цитатами и наши итоги", async () => {
    const q = [{ quote: "[цитата]", doc_id: "d1", title: "[статья]", year: 2024, url: "" }];
    const link = (relation: string, documents: number) => ({ from: "[фактор]", relation, to: "[результат]", hedged: false, documents, quotes: q });
    const summary = {
      factor: "[фактор]", outcome: "[результат]", total: 10, leader: "up", agreement: 0.6,
      groups: [
        { key: "up", documents: 6, links: [link("повышает", 6)] },
        { key: "down", documents: 2, links: [link("снижает", 2)] },
        { key: "none", documents: 2, links: [link("не влияет", 2)] },
        { key: "other", documents: 0, links: [] },
      ],
      experiments: [{ code: "EXP-001", title: "[проверка]", status: "done", outcome: "rejected" }],
      hypotheses: [],
      findings: [
        { kind: "disputed", leader: "up", agreement: 0.6 },
        { kind: "check_against", code: "EXP-001", idea: "H-001", outcome: "rejected", claims: "up" },
      ],
    };
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        urls.push(url);
        if (url.includes("/auth/me")) return Promise.resolve(json(user("reader")));
        if (url.includes("/kb/network")) {
          // «[задание]» — слово из названия пункта: подсказывается; «[другое]» — нет; статья — не понятие
          const nodes = [
            { id: "e1", kind: "сущность", name: "[задание]", documents: 12, spellings: [] },
            { id: "e2", kind: "сущность", name: "[другое]", documents: 99, spellings: [] },
            { id: "a1", kind: "статья", name: "[задание]" },
          ];
          return Promise.resolve(json({ nodes, edges: [] }));
        }
        if (url.includes("/articles?")) return Promise.resolve(json(summary));
        if (url.includes("/methodology") && !url.includes("versions") && !url.includes("change")) return Promise.resolve(json(TREE));
        return Promise.resolve(json([]));
      }),
    );
    window.location.hash = "#articles-Н1.В1.З1";
    renderAt("/methodology");
    expect(await screen.findByRole("tab", { name: "Что говорят статьи" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(await screen.findByRole("button", { name: "[задание] · 12 статей" }));
    expect(screen.queryByRole("button", { name: /\[другое\]/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Фактор — что влияет")).toHaveValue("[задание]");
    await userEvent.type(screen.getByLabelText("Результат — на что влияет"), "[[результат]");
    expect(screen.getByLabelText("Результат — на что влияет")).toHaveValue("[результат]");
    await userEvent.click(screen.getByRole("button", { name: "Показать, что говорят статьи" }));
    expect(await screen.findByText(/Статьи расходятся: чаще всего говорят «повышает», но только 60 %/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "повышает: 6 статей, снижает: 2 статьи, не влияет: 2 статьи" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "[статья]" })[0]).toHaveAttribute("href", "/knowledge/article/d1");
    expect(screen.getByText(/расходится с большинством статей/)).toBeInTheDocument();
    // читателю предлагать изменение нельзя
    expect(screen.queryByRole("button", { name: "Предложить изменение пункта по статьям" })).not.toBeInTheDocument();
    expect(urls.some((u) => u.includes("/methodology/sections/%D0%9D1.%D0%921.%D0%971/articles?factor="))).toBe(true);
  });

  it("исследователь предлагает изменение пункта по статьям — с цитатами-основаниями", async () => {
    const q = [
      { quote: "[цитата]", doc_id: "d1", title: "[статья]", year: 2024, url: "https://doi.org/10.0000/[doi]" },
      { quote: "[цитата]", doc_id: "d2", title: "[статья без DOI]", year: 2024, url: "" },
    ];
    const summary = {
      factor: "[фактор]", outcome: "[результат]", total: 4, leader: "up", agreement: 1,
      groups: [
        { key: "up", documents: 4, links: [{ from: "[фактор]", relation: "повышает", to: "[результат]", hedged: false, documents: 4, quotes: q }] },
        { key: "down", documents: 0, links: [] },
        { key: "none", documents: 0, links: [] },
        { key: "other", documents: 0, links: [] },
      ],
      experiments: [], hypotheses: [], findings: [{ kind: "consensus", leader: "up", agreement: 1 }, { kind: "unchecked" }],
    };
    const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          posts.push({ url, body: JSON.parse(String(init.body)) as Record<string, unknown> });
          return Promise.resolve(json({ ...CR, code: "CR-02" }, url.endsWith("/change-requests") ? 201 : 200));
        }
        if (url.includes("/auth/me")) return Promise.resolve(json(user("researcher")));
        if (url.includes("/kb/network")) return Promise.resolve(json({ nodes: [], edges: [] }));
        if (url.includes("/articles?")) return Promise.resolve(json(summary));
        if (url.includes("/methodology") && !url.includes("versions") && !url.includes("change")) return Promise.resolve(json(TREE));
        return Promise.resolve(json([]));
      }),
    );
    window.location.hash = "#articles-Н1.В1.З1";
    renderAt("/methodology");
    await userEvent.type(await screen.findByLabelText("Фактор — что влияет"), "[[фактор]");
    await userEvent.type(screen.getByLabelText("Результат — на что влияет"), "[[результат]");
    await userEvent.click(screen.getByRole("button", { name: "Показать, что говорят статьи" }));
    expect(await screen.findByText(/У нас это ещё не проверено/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Предложить изменение пункта по статьям" }));
    const send = screen.getByRole("button", { name: "Отправить предложение" });
    expect(send).toBeDisabled(); // текст пункта ещё не изменён
    expect(screen.getByRole("checkbox", { name: /\[статья\]: «\[фактор\]» — повышает — «\[результат\]»/ })).toBeChecked();
    // статья без DOI «требует источника» — отметить нельзя
    expect(screen.getByRole("checkbox", { name: /\[статья без DOI\]/ })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Новый текст пункта"), " [[уточнение по статьям]");
    await userEvent.click(send);
    expect(await screen.findByText(/Предложение/)).toBeInTheDocument();
    expect(posts.map((p) => p.url)).toEqual(["/api/change-requests", "/api/change-requests/CR-02/bases"]);
    expect(posts[0]?.body).toMatchObject({ section: "Н1.В1.З1", proposed_content: "[текст пункта] [уточнение по статьям]" });
    expect(posts[1]?.body).toEqual({
      basis_type: "kb_article", kbrag_id: "d1", kb_path: "esg", title: "[статья]", doi: "10.0000/[doi]",
      quote: "«[фактор]» — повышает — «[результат]»: «[цитата]»",
    });
    expect(screen.getByRole("button", { name: "Открыть CR-02" })).toBeInTheDocument();
  });

  it("ссылка на предложение из отчёта сразу открывает его вкладку", async () => {
    window.location.hash = "#cr-CR-01";
    stub("reader", routes);
    renderAt("/methodology");
    expect(await screen.findByText("[что меняется]")).toBeInTheDocument();
  });
});
