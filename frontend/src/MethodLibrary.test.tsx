import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только поведение библиотеки методов
const user = (role: string) => ({ id: 1, login: "[логин]", full_name: "", email: "", role, nda_access: false });
const METHOD = {
  code: "M-01", key: "method:M-01", title: "[LSTM авторов]", description: "[описание]", net: "lstm",
  net_title: "Рекуррентная сеть (LSTM, GRU)", task: "predict",
  params: [{ name: "hidden", label: "[нейронов]", default: 32, min: 1, max: 512, hint: "" }],
  status: "ready", check_log: "[пробный запуск без сети: R² 0,42]", sha256: "a".repeat(64), doc_id: "[статья]",
  article_title: "[название статьи]", doi: "10.0000/[x]", evidence: "[цитата авторов о модели]", author: "",
  decided_by: "", decision_note: "", created_at: "2026-11-15T00:00:00Z", script: "",
};
const LIB = { builtin: [{ key: "lab-mlp", title: "[метод лаборатории]", description: "[описание]" }], methods: [METHOD], pending: [] };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(role: string, onEnable = vi.fn()) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(user(role)));
      if (url.endsWith("/methods/M-01/enable") && init?.method === "POST") {
        onEnable();
        return Promise.resolve(json({ ...METHOD, status: "enabled" }));
      }
      if (url.endsWith("/methods/M-01")) return Promise.resolve(json({ ...METHOD, script: "TITLE = \"[код метода]\"" }));
      if (url.endsWith("/methods")) return Promise.resolve(json(LIB));
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

describe("Библиотека методов", () => {
  it("администратор видит метод из статьи с источником и кодом и включает его", async () => {
    const onEnable = vi.fn();
    stub("owner", onEnable);
    renderAt("/nets/library");
    const card = await screen.findByRole("article", { name: "M-01 [LSTM авторов]" });
    expect(within(card).getByText("проверен, ждёт администратора")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "[название статьи]" })).toHaveAttribute("href", "/knowledge/article/%5B%D1%81%D1%82%D0%B0%D1%82%D1%8C%D1%8F%5D");
    expect(within(card).getByText(/\[цитата авторов о модели\]/)).toBeInTheDocument();
    expect(within(card).getByText(/\[нейронов\] = 32/)).toBeInTheDocument();
    await userEvent.click(within(card).getByText("Код метода"));
    expect(await within(card).findByText(/\[код метода\]/)).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Код прочитан — включить" }));
    expect(onEnable).toHaveBeenCalled();
    // вкладка — внутри «Нейросетей»
    const tabs = screen.getByRole("navigation", { name: "Разделы вкладки «Нейросети»" });
    expect(within(tabs).getByRole("link", { name: "Библиотека методов" })).toHaveClass("active");
  });

  it("исследователь видит метод, но включить не может", async () => {
    stub("researcher");
    renderAt("/nets/library");
    await screen.findByRole("article", { name: "M-01 [LSTM авторов]" });
    expect(screen.queryByRole("button", { name: "Код прочитан — включить" })).not.toBeInTheDocument();
  });
});
