import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется, что последний шаг цикла виден на карточке идеи
const USER = { id: 1, login: "[логин]", full_name: "", email: "", role: "reader", nda_access: false };
const IDEA = {
  code: "H-003", title: "[идея]", statement: "[утверждение]", rationale: "", direction: "", status: "tested",
  decision_note: "", author: "", decided_by: "", experiment: "EXP-009", methodology_node: "", methodology_node_title: "",
  source: "", suggested: {}, created_at: "2026-11-15T00:00:00Z", refs: [], effect: "", target_kind: "", weight: null,
  weight_set_by: "",
};
const cr = (code: string, status: string, ref: string) => ({
  code, section: "", section_title: "", action: "add", new_kind: "section", new_title: "[пункт]", title: `[${code}]`,
  description: "", proposed_content: "", status, target_version: status === "accepted" ? "0.2" : "",
  bases: [{ basis_type: "experiment", ref, valid: true }], reviews: [], blockers: [], source: "", report: "",
  report_experiment: "", problems: "", author: "", editable: false,
});
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function stub(crs: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(USER));
      if (url.includes("/change-requests")) return Promise.resolve(json(crs));
      if (url.includes("/hypotheses")) return Promise.resolve(json([IDEA]));
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

describe("Последний шаг цикла", () => {
  it("по проверке идеи принят CR — карточка говорит, что цикл закрыт, и называет версию методики", async () => {
    stub([cr("CR-02", "accepted", "EXP-009"), cr("CR-03", "review", "EXP-777")]);
    renderAt("/hypotheses");
    expect(await screen.findByText(/Цикл закрыт: по этой проверке изменена методика/)).toBeInTheDocument();
    expect(screen.getByText(/«\[CR-02\]», принято, версия методики 0\.2/)).toBeInTheDocument();
    expect(screen.queryByText(/CR-03/)).not.toBeInTheDocument(); // чужая проверка
  });

  it("предложения нет — прежняя подсказка: можно предложить изменение методики", async () => {
    stub([]);
    renderAt("/hypotheses");
    expect(await screen.findByText(/по отчёту можно предложить изменение методики/)).toBeInTheDocument();
  });
});
