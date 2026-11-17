import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только поведение вкладки «Нейросети»
const user = (role: string) => ({ id: 1, login: "[логин]", full_name: "", email: "", role, nda_access: false });
const TEMPLATE = {
  key: "correlation-scan", title: "[поиск связей]", description: "", scope: "generic", experiment: "", dataset: "",
  resource: "cpu", limit_min: 60, params: [],
  snapshots: [{ id: 5, dataset: "DS-09", version: "[версия]", sha256: "a".repeat(64), row_count: 600 }],
};
const RECO = {
  snapshot: { id: 5, dataset: "DS-09", title: "[набор]", version: "[версия]" },
  columns: ["[страна]", "[год]", "[a]", "[b]", "[c]"], numeric: ["[год]", "[a]", "[b]", "[c]"], categories: [], sheet: "",
  sheets: [], rows: 600, target_candidates: [], task: { key: "agreement", title: "[задача]", text: "[что делаем]" },
  recommendations: [
    { key: "correlation-scan", template: "correlation-scan", title: "[поиск связей]", method_title: "[метод]",
      params: { columns: ["[a]", "[b]", "[c]"], group: "[страна]", sheet: "" }, why: ["[почему]"], warnings: [],
      primary: false, runnable: true, net: "" },
  ],
};
const link = (a: string, b: string) => ({ a, b, kind: "монотонная", rho: 0.6, xi: 0.4, rho_confirm: 0.55, xi_confirm: 0.3, n: 50 });
const net = (key: string, r2: number, holds: boolean) => ({
  run_id: 7, status: "done", net: key, title: `[${key}]`, r2, placebo: 0.05, holds,
});
const LINKS = {
  snapshot: { id: 5, dataset: "DS-09", title: "[набор]", version: "[версия]" },
  scan: {
    run_id: 3, status: "done", message: "", group: "[страна]", unit: "group", rows_find: 50, rows_confirm: 50, pairs: 3,
    found: 2, confirmed: 2, panel_hint: "", not_confirmed_total: 0, links_total: 2,
    links: [link("[a]", "[b]"), link("[a]", "[c]")],
  },
  checks: [
    {
      experiment: "EXP-011", a: "[a]", b: "[b]", target: "[b]", held: 3, finished: 5, total: 5,
      nets: [net("mlp", 0.41, true), net("transformer", 0.02, false), net("gbm", 0.03, false), net("linear", 0.38, true),
        { ...net("method:M-01", 0.44, true), title: "[LSTM авторов]" }],
    },
  ],
};
const option = (id: string, recommended: boolean, minutes: number) => ({
  id, net: id, title: `[${id}]`, minutes, note: "", runnable: true, warnings: [], recommended, done: false,
});
const NET_MENU = { nets: [option("mlp", true, 12), option("transformer", false, 90), option("gbm", true, 2)], existing: null, existing_status: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(role: string, links: unknown = LINKS, onCheck = vi.fn(), onScan = vi.fn(), onLinks = vi.fn()) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(user(role)));
      if (url.includes("/run-templates")) return Promise.resolve(json([TEMPLATE]));
      if (url.includes("/analysis/recommend")) return Promise.resolve(json(RECO));
      if (url.includes("/analysis/links")) {
        onLinks(url);
        return Promise.resolve(json(links));
      }
      if (url.includes("/analysis/link-nets")) return Promise.resolve(json(NET_MENU));
      if (url.includes("/analysis/link-check")) {
        onCheck(JSON.parse(String(init?.body)));
        return Promise.resolve(json({ experiment: "EXP-012", run_ids: [8, 9, 10] }, 201));
      }
      if (url.includes("/analysis/launch")) {
        onScan(JSON.parse(String(init?.body)));
        return Promise.resolve(json({ experiment: "EXP-013", run_id: 4 }, 201));
      }
      return Promise.resolve(json([]));
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

afterEach(() => vi.unstubAllGlobals());

describe("Нейросети", () => {
  it("связи из поиска — таблицей «связь × сеть»; непроверенную связь можно проверить набором сетей", async () => {
    const onCheck = vi.fn();
    stub("researcher", LINKS, onCheck);
    renderAt("/nets?snapshot=5");
    expect(await screen.findByRole("heading", { name: "Нейросети", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText(/каждая «\[страна\]» — одно наблюдение/)).toBeInTheDocument();
    expect(screen.getByText(/наблюдение — «\[страна\]»/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Связи из поиска и их проверка сетями" });
    const checked = within(table).getByRole("rowheader", { name: /«\[a\]» — «\[b\]»/ }).closest("tr") as HTMLElement;
    expect(within(checked).getByText("держится у 3 из 5")).toBeInTheDocument();
    // метод из библиотеки (статья банка) — своим столбцом
    expect(within(table).getByRole("columnheader", { name: "[LSTM авторов]" })).toBeInTheDocument();
    expect(within(checked).getByText(/R² 0,44, на перемешанной цели 0,05 — держится/)).toBeInTheDocument();
    expect(within(checked).getByText(/R² 0,41, на перемешанной цели 0,05 — держится/)).toBeInTheDocument();
    expect(within(checked).getByText(/R² 0,02, на перемешанной цели 0,05 — не держится/)).toBeInTheDocument();
    expect(within(checked).getByRole("link", { name: "EXP-011" })).toHaveAttribute("href", "/experiments/EXP-011");

    // сети выбирает человек: что предсказываем, какими сетями, сколько это займёт
    const fresh = within(table).getByRole("rowheader", { name: /«\[a\]» — «\[c\]»/ }).closest("tr") as HTMLElement;
    await userEvent.click(within(fresh).getByRole("button", { name: "Выбрать сети и проверить" }));
    const picker = await screen.findByRole("group", { name: "Какими сетями проверить" });
    await userEvent.click(screen.getByRole("radio", { name: /«\[a\]» по «\[c\]» и остальным показателям/ }));
    const mlp = await within(picker).findByRole("checkbox", { name: /\[mlp\]/ });
    expect(mlp).toBeChecked();
    expect(within(picker).getByRole("checkbox", { name: /\[transformer\]/ })).not.toBeChecked();
    expect(within(picker).getByText(/Нейросеть лаборатории/)).toBeInTheDocument();
    await userEvent.click(within(picker).getByRole("checkbox", { name: /\[gbm\]/ }));
    await userEvent.click(within(picker).getByRole("checkbox", { name: /\[transformer\]/ }));
    expect(screen.getByText(/в сумме ≈ 102 мин расчёта/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Проверить: 2 сети" }));
    expect(onCheck).toHaveBeenCalledWith({ scan_run: 3, a: "[a]", b: "[c]", target: "[a]", node: "", nets: ["mlp", "transformer"] });

    // шаг 4: связь, которая держится, — в идею, с итогами сетей в обосновании
    await userEvent.click(screen.getByRole("button", { name: "Предложить идеей" }));
    expect((await screen.findByLabelText("Обоснование") as HTMLTextAreaElement).value).toMatch(
      /Проверка сетями \(EXP-011\), предсказывали «\[b\]»: держится у 3 из 5 — \[mlp\]: R² 0,41/,
    );
  });

  it("поиска ещё не было — одна кнопка «Найти связи» с группой панели; читатель только смотрит", async () => {
    const onScan = vi.fn();
    stub("researcher", { ...LINKS, scan: null, checks: [] }, vi.fn(), onScan);
    const { unmount } = renderAt("/nets?snapshot=5");
    await userEvent.click(await screen.findByRole("button", { name: "Найти связи" }));
    expect(onScan).toHaveBeenCalledWith(
      expect.objectContaining({
        template: "correlation-scan",
        params: { columns: ["[a]", "[b]", "[c]"], group: "[страна]", sheet: "", method: "rank" },
      }),
    );
    unmount();
    stub("reader", LINKS);
    renderAt("/nets?snapshot=5");
    expect(await screen.findByText("держится у 3 из 5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Выбрать сети и проверить" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Добавить сеть" })).not.toBeInTheDocument();
    expect(screen.getByText("не проверялась")).toBeInTheDocument();
  });

  it("вкладки раздела названы по задаче: найти связи или предсказать показатель", async () => {
    stub("researcher");
    renderAt("/analysis");
    const tabs = await screen.findByRole("navigation", { name: "Разделы вкладки «Нейросети»" });
    expect(within(tabs).getByRole("link", { name: "Найти и проверить связи" })).toHaveAttribute("href", "/nets");
    expect(within(tabs).getByRole("link", { name: "Предсказать один показатель" })).toHaveClass("active");
    expect(screen.getByRole("heading", { name: "Предсказать один показатель", level: 1 })).toBeInTheDocument();
  });

  it("способов поиска несколько: у каждого — как работает, когда подходит и чего не видит", async () => {
    const onLinks = vi.fn();
    const onScan = vi.fn();
    const scans = [{ method: "rank", run_id: 3, status: "done", confirmed: 2, pairs: 3 }];
    stub("researcher", { ...LINKS, scans }, vi.fn(), onScan, onLinks);
    renderAt("/nets?snapshot=5");
    const methods = await screen.findByRole("group", { name: "Каким способом искать связи" });
    expect(within(methods).getByRole("radio", { name: /Любые связи/ })).toBeChecked();
    expect(within(methods).getByText("нашёл: 2")).toBeInTheDocument();
    expect(within(methods).getAllByText("Не видит")).toHaveLength(3);
    expect(screen.getByText(/Способ «Любые связи»: подтверждено/)).toBeInTheDocument();
    await userEvent.click(within(methods).getByRole("radio", { name: /Без влияния остальных показателей/ }));
    expect(onLinks).toHaveBeenLastCalledWith(expect.stringContaining("method=partial"));
    expect(screen.getByText(/Как поиск отличает связь от случайности/)).toBeInTheDocument();
  });
});
