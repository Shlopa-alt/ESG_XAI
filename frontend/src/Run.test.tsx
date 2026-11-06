import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только поведение мастера
const USER = { id: 1, login: "[researcher]", full_name: "", email: "", role: "researcher", nda_access: false };
const HYP = {
  code: "H-001",
  title: "[гипотеза]",
  statement: "[утверждение]",
  rationale: "",
  direction: "",
  status: "accepted",
  decision_note: "",
  author: "",
  decided_by: "",
  experiment: "",
  methodology_node: "",
  source: "qwen",
  suggested: {},
  created_at: "2026-11-01T00:00:00Z",
  refs: [],
};
const PROPOSAL = {
  id: 7,
  hypothesis: "H-001",
  status: "proposed",
  title: "[эксперимент]",
  method: "rank-agreement",
  method_title: "[метод]",
  snapshot_id: 1,
  snapshot: "DS-01 · [срез]",
  params: {},
  setup: [],
  expected: "",
  rationale: "",
  problems: "",
  note: "",
  decided_by: "",
  experiment: "",
  run_id: null,
  created_at: "2026-11-01T00:00:00Z",
};

const RUN = {
  id: 5,
  experiment: "EXP-009",
  status: "queued",
  resource: "cpu",
  template: "rank-agreement",
  config: { params: {} },
  runner_commit: "",
  dataset: "",
  dataset_sha256: "",
  env_lock_sha256: "",
  python: "",
  seeds: {},
  parts: {},
  summary: {},
  results_path: "",
  mlflow_run_id: "",
  message: "",
  author: "",
  started_at: null,
  finished_at: null,
  created_at: null,
  reproducible: false,
  note: "",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function api(proposals: unknown[], onApprove = vi.fn()) {
  return vi.fn((url: string, init?: RequestInit) => {
    if (url.includes("/auth/me")) return Promise.resolve(json(USER));
    if (url.includes("/hypotheses")) return Promise.resolve(json([HYP]));
    if (url.includes("/approve")) {
      onApprove(init);
      return Promise.resolve(json({ ...PROPOSAL, status: "approved", experiment: "EXP-009", run_id: 5 }));
    }
    if (url.includes("/experiment-proposals")) return Promise.resolve(json(proposals));
    if (/\/runs\/\d+$/.test(url)) return Promise.resolve(json(RUN));
    return Promise.resolve(json([]));
  });
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

describe("Мастер запуска", () => {
  it("показывает предложение Qwen и одобряет его одной кнопкой", async () => {
    const onApprove = vi.fn();
    vi.stubGlobal("fetch", api([PROPOSAL], onApprove));
    // после одобрения открывается страница запуска с живым потоком — в jsdom его нет
    vi.stubGlobal("EventSource", class { close() {} });
    renderAt("/run?h=H-001");
    expect(await screen.findByText("[метод]")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Создать эксперимент и запустить" }));
    expect(onApprove).toHaveBeenCalledTimes(1);
    // сразу переходим на страницу запуска с понятным «что дальше»
    expect(await screen.findByText(/стоит в очереди сервера/)).toBeInTheDocument();
  });

  it("пока Qwen думает — объясняет, что ждать, и предлагает задать вручную", async () => {
    vi.stubGlobal("fetch", api([]));
    renderAt("/run");
    expect(await screen.findByText(/Qwen готовит предложение эксперимента/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать эксперимент и запустить" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Задам сам" }));
    expect(screen.getByRole("combobox", { name: "Метод" })).toBeInTheDocument();
  });
});
