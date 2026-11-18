import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только схема на вкладке «Как мы исследуем»
const node = (number: string, kind: string, parent: string) => ({
  number, kind, parent, title: `[${number}]`, content: "[текст]", stability: "draft", position: 0,
});
const TREE = {
  version: "[версия]",
  sections: [
    node("Н1", "direction", ""),
    node("Н1.В1", "variant", "Н1"),
    node("Н1.В2", "variant", "Н1"),
    node("Н1.В1.З1", "task", "Н1.В1"),
    node("01", "section", ""),
  ],
};
const cr = (code: string, status: string) => ({
  code, section: "01", action: "edit", new_kind: "", new_title: "", title: "[что меняется]", description: "", status,
  proposed_content: "", author: "", source: "", report: "", report_experiment: "", target_version: "", bases: [], reviews: [],
  blockers: [], problems: "", editable: false,
});
const exp = (code: string, outcome: string | null) => ({
  code, title: "[проверка]", hypothesis: "", direction: "", status: "review", outcome, data_summary: "", conclusion: "", methodology_node: "",
});

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function renderMethodology() {
  const routes: Record<string, unknown> = {
    "/auth/me": { id: 1, login: "[логин]", full_name: "", email: "", role: "reader", nda_access: false },
    "/change-requests": [cr("CR-01", "proposed"), cr("CR-02", "accepted")],
    "/methodology/versions": [{ version: "[в1]", notes: "[заметка о версии]", created_at: "2026-11-01T00:00:00Z" }],
    "/methodology": TREE,
    "/experiments": [exp("EXP-001", "rejected"), exp("EXP-002", null)],
    "/hypotheses": [{ code: "H-01" }, { code: "H-02" }, { code: "H-03" }],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const key = Object.keys(routes).find((k) => url.includes(k));
      return Promise.resolve(json(key ? routes[key] : []));
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/methodology"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("схема методики", () => {
  it("показывает строение и круг изменений с настоящими числами", async () => {
    renderMethodology();
    const scheme = await screen.findByRole("region", { name: "Как устроена методика" });
    const tree = within(scheme).getByRole("heading", { name: "Из чего она состоит" }).parentElement as HTMLElement;
    expect(within(tree).getByText("Направление").parentElement).toHaveTextContent("1");
    expect(within(tree).getByText("Вариант").parentElement).toHaveTextContent("2");
    expect(within(tree).getByText("Задание").parentElement).toHaveTextContent("1");
    expect(tree).toHaveTextContent("Сейчас правил: 1");
    expect(within(scheme).getByRole("link", { name: /Идея/ })).toHaveTextContent("3");
    expect(within(scheme).getByRole("link", { name: /Проверка/ })).toHaveAttribute("href", "/experiments");
    expect(within(scheme).getByRole("link", { name: /Рецензия/ })).toHaveTextContent("1");
    expect(within(scheme).getByRole("button", { name: /Предложение/ })).toHaveTextContent("1");
    expect(scheme).toHaveTextContent("Принято изменений: 1");
  });

  it("шаги «Предложение» и «Новая версия» открывают вкладки этой страницы", async () => {
    renderMethodology();
    const scheme = await screen.findByRole("region", { name: "Как устроена методика" });
    await userEvent.click(within(scheme).getByRole("button", { name: /Новая версия/ }));
    expect(await screen.findByText(/\[заметка о версии\]/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "История версий" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Как мы исследуем" }));
    const again = await screen.findByRole("region", { name: "Как устроена методика" });
    await userEvent.click(within(again).getByRole("button", { name: /Предложение/ }));
    expect(screen.getByRole("tab", { name: /Предложения изменений/ })).toHaveAttribute("aria-selected", "true");
  });
});
