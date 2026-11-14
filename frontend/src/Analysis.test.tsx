import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только поведение экрана анализа
const user = (role: string) => ({ id: 1, login: "[логин]", full_name: "", email: "", role, nda_access: false });
const TEMPLATE = {
  key: "lab-mlp", title: "[метод лаборатории]", description: "", scope: "generic", experiment: "", dataset: "",
  resource: "cpu", limit_min: 240, params: [],
  snapshots: [{ id: 5, dataset: "DS-09", version: "[версия]", sha256: "a".repeat(64), row_count: 40 }],
};
const RECO = {
  snapshot: { id: 5, dataset: "DS-09", title: "[набор]", version: "[версия]" },
  columns: ["[R]", "[x]"], numeric: ["[R]", "[x]"], categories: [], sheet: "", sheets: [], rows: 40,
  target_candidates: [], task: { key: "predict", title: "Прогноз числового показателя", text: "[что делаем]" },
  recommendations: [
    { key: "lab-mlp", template: "lab-mlp", title: "[нейросеть лаборатории]", method_title: "[метод]", params: {},
      why: ["[почему этот метод]"], warnings: [], primary: true, runnable: true, net: "" },
    { key: "predictive-check", template: "predictive-check", title: "[быстрая проверка]", method_title: "[метод 2]",
      params: {}, why: ["[почему альтернатива]"], warnings: [], primary: false, runnable: true, net: "" },
  ],
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(role: string, onLaunch = vi.fn()) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(user(role)));
      if (url.includes("/run-templates")) return Promise.resolve(json([TEMPLATE]));
      if (url.includes("/analysis/recommend")) return Promise.resolve(json(RECO));
      if (url.includes("/analysis/launch")) {
        onLaunch(JSON.parse(String(init?.body)));
        return Promise.resolve(json({ experiment: "EXP-009", run_id: 3 }, 201));
      }
      if (url.includes("/runs/3")) return Promise.resolve(json({ detail: "[нет]" }, 404));
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

describe("Анализ данных", () => {
  it("по набору данных показывает рекомендацию с причиной и запускает расчёт одной кнопкой", async () => {
    const onLaunch = vi.fn();
    stub("researcher", onLaunch);
    vi.stubGlobal("EventSource", class { close() {} });
    renderAt("/analysis");
    await screen.findByRole("option", { name: /DS-09/ });
    await userEvent.selectOptions(screen.getByLabelText("Набор данных и версия"), "5");
    expect(await screen.findByText("[почему этот метод]")).toBeInTheDocument();
    expect(screen.getByText("Рекомендуем")).toBeInTheDocument();
    expect(screen.getByText("Альтернатива")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Запустить расчёт" })[0] as HTMLElement);
    expect(onLaunch).toHaveBeenCalledTimes(1);
    expect(onLaunch.mock.calls[0]?.[0]).toMatchObject({ snapshot_id: 5, template: "lab-mlp", choice: { primary: true, why: ["[почему этот метод]"] } });
  });

  it("читателю показывает рекомендации без кнопки запуска", async () => {
    stub("reader");
    renderAt("/analysis");
    await screen.findByRole("option", { name: /DS-09/ });
    await userEvent.selectOptions(screen.getByLabelText("Набор данных и версия"), "5");
    expect(await screen.findByText("[почему этот метод]")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Запустить расчёт" })).toBeNull();
  });
});

describe("Подбор сети по статье", () => {
  const IDEA = {
    code: "H-001", title: "[идея]", statement: "[утверждение]", rationale: "", direction: "", status: "accepted",
    decision_note: "", author: "", decided_by: "", experiment: "", methodology_node: "", source: "qwen",
    suggested: { dataset: "DS-09" }, created_at: "2026-11-01T00:00:00Z",
    refs: [{ kind: "article", kbrag_id: "[doc]", title: "[статья]", doi: "", quote: "" }],
  };
  const AUTHORS_RECO = {
    ...RECO,
    authors: { net: "transformer", title: "[трансформер]", quote: "[цитата]", runnable: true, nearest_title: "",
      article_title: "[статья]", doc_id: "[doc]" },
    authors_note: "",
    hypothesis: { code: "H-001", title: "[идея]", statement: "[утверждение]", status: "accepted", node: "" },
    recommendations: [
      { key: "authors:transformer", template: "lab-mlp", title: "Как у авторов: [трансформер]", method_title: "[метод]",
        params: {}, why: ["[цитата из статьи]"], warnings: [], primary: true, runnable: true, net: "transformer",
        as_authors: true, evidence: "[цитата]" },
      { ...RECO.recommendations[0], key: "lab-mlp:mlp", primary: false, net: "mlp", as_authors: false, evidence: "" },
    ],
  };

  it("по идее со статьёй подставляет её данные и первой ставит «как у авторов»; выбор уходит в проверку", async () => {
    const onLaunch = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url.includes("/auth/me")) return Promise.resolve(json(user("researcher")));
        if (url.includes("/run-templates")) return Promise.resolve(json([TEMPLATE]));
        if (url.includes("/hypotheses")) return Promise.resolve(json([IDEA]));
        if (url.includes("/analysis/recommend")) return Promise.resolve(json(AUTHORS_RECO));
        if (url.includes("/analysis/launch")) {
          onLaunch(JSON.parse(String(init?.body)));
          return Promise.resolve(json({ experiment: "EXP-009", run_id: 3 }, 201));
        }
        return Promise.resolve(json([]));
      }),
    );
    vi.stubGlobal("EventSource", class { close() {} });
    renderAt("/analysis?h=H-001");
    expect(await screen.findByText("Как у авторов: [трансформер]")).toBeInTheDocument();
    expect(screen.getByText("Как у авторов")).toBeInTheDocument();
    expect(screen.getByLabelText("Набор данных и версия")).toHaveValue("5");
    await userEvent.click(screen.getAllByRole("button", { name: "Запустить расчёт" })[0] as HTMLElement);
    expect(onLaunch.mock.calls[0]?.[0]).toMatchObject({
      hypothesis: "H-001",
      choice: { as_authors: true, net: "transformer", evidence: "[цитата]", article: "[статья]" },
    });
  });
});
