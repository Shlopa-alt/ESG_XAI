import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется, что ход проверки и вывод видны (п. 12–13 фидбека)
const user = { id: 1, login: "[логин]", full_name: "", email: "", role: "researcher", nda_access: false };
const base = {
  title: "[проверка]", hypothesis: "", direction: "", outcome: null, method: "", data_summary: "", dataset_snapshot_id: null,
  seed: null, runner_commit: "", env_lock: "", setup: [], results: [], conclusion: "", limitations: [], reproducibility: [],
  report_path: "", methodology_node: "", report: {}, config: {}, reviews: [], links: [], dataset_snapshot: "",
};
const RUNNING = {
  ...base, code: "EXP-010", status: "running", draft: null,
  progress: { total: 3, done: 1, failed: 0, left_min: 118, active: [
    { run_id: 12, status: "running", title: "[нейросеть]", elapsed_min: 40, estimate_min: 147 },
    { run_id: 13, status: "queued", title: "[быстрая проверка]", elapsed_min: 0, estimate_min: 11 },
  ] },
};
const FINISHED = {
  ...base, code: "EXP-009", status: "review", progress: { total: 1, done: 1, failed: 0, left_min: 0, active: [] },
  draft: { version: 1, status: "draft", verdict: "confirmed", summary: "[найдено 29 связей]", verdict_reason: "" },
};
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(user));
      if (url.endsWith("/experiments/EXP-010")) return Promise.resolve(json(RUNNING));
      if (url.endsWith("/experiments/EXP-009")) return Promise.resolve(json(FINISHED));
      if (url.endsWith("/experiments")) return Promise.resolve(json([RUNNING, FINISHED]));
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

describe("Ход и вывод проверки", () => {
  it("в списке у проверки в работе видно, что готово, что идёт и сколько осталось", async () => {
    stub();
    renderAt("/experiments");
    expect(await screen.findByText(/Готово расчётов: 1 из 3/)).toBeInTheDocument();
    expect(screen.getByText(/Идёт «\[нейросеть\]» — 40 мин из ~147 мин/)).toBeInTheDocument();
    expect(screen.getByText(/Осталось примерно 118 мин/)).toBeInTheDocument();
  });

  it("законченная проверка показывает предварительный вывод отчёта", async () => {
    stub();
    renderAt("/experiments/EXP-009");
    expect(await screen.findByText(/\[найдено 29 связей\]/)).toBeInTheDocument();
    expect(screen.getByText(/Предварительный вывод ИИ-помощника/)).toBeInTheDocument();
  });
});
