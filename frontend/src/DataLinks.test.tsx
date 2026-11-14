import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только поведение экрана «Данные из статей»
const user = (role: string) => ({ id: 1, login: "[логин]", full_name: "", email: "", role, nda_access: false });
const ITEM = {
  id: 7, status: "proposed", title: "", article_title: "[статья]", doi: "10.0000/[x]", doc_id: "[doc]", table_number: 0,
  page: null, n_rows: 0, n_cols: 0, dataset: "", created_at: "2026-11-01T00:00:00Z", source_kind: "link",
  source_url: "https://data.mendeley.com/datasets/[x]",
};
const DRAFT = {
  ...ITEM, kb_path: "esg", caption: "", description: "", columns: [], rows: [], numeric: [], note: "", decided_by: "",
  decided_at: null, jobs: [], link_context: "[The data are available at Mendeley Data]", file_url: "", file_name: "",
  file_sha256: "",
  history: [
    { at: "2026-11-01T00:00:00Z", who: "агент сбора данных", kind: "found", text: "[ссылка найдена в статье]" },
    { at: "2026-11-01T00:00:00Z", who: "агент сбора данных", kind: "download", text: "Файл не скачан: [вход по логину]" },
  ],
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(role: string, onScan = vi.fn()) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(user(role)));
      if (url.includes("/data-drafts/links-scan")) {
        onScan(init?.body);
        return Promise.resolve(json({ job: 12 }, 202));
      }
      if (url.includes("/data-drafts/7")) return Promise.resolve(json(DRAFT));
      if (url.includes("/data-drafts")) return Promise.resolve(json([ITEM]));
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

describe("Данные по ссылкам из статей", () => {
  it("администратор запускает поиск; в списке видно, что черновик — ссылка на данные", async () => {
    const onScan = vi.fn();
    stub("owner", onScan);
    renderAt("/data-drafts");
    expect(await screen.findByText("ссылка на данные")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Данные по ссылке из статьи" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Найти данные по ссылкам из статей" }));
    expect(onScan).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Задача ИИ-помощника №12 в очереди/)).toBeInTheDocument();
  });

  it("черновик показывает статью, источник, что файл не скачан, и условия статьи", async () => {
    stub("researcher");
    renderAt("/data-drafts/7");
    expect(await screen.findByRole("heading", { name: "Откуда данные" })).toBeInTheDocument();
    const articles = screen.getAllByRole("link", { name: "[статья]" }).map((a) => a.getAttribute("href"));
    expect(articles).toContain("/knowledge/article/%5Bdoc%5D");
    expect(screen.getByRole("link", { name: ITEM.source_url })).toHaveAttribute("href", ITEM.source_url);
    expect(screen.getByText(/не скачан автоматически/)).toBeInTheDocument();
    expect(screen.getByText(/Условия использования определяет статья/)).toBeInTheDocument();
    expect(screen.getByText("Файл не скачан: [вход по логину]")).toBeInTheDocument();
  });
});
