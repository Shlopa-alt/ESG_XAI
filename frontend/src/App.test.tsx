import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const USER = {
  id: 1,
  login: "ivanov",
  full_name: "Иван Иванов",
  email: "",
  role: "researcher",
  nda_access: false,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderApp(path = "/") {
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

describe("App", () => {
  it("показывает форму входа без сессии", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Требуется вход" }, 401)));
    renderApp();
    expect(await screen.findByLabelText("Логин")).toBeInTheDocument();
    expect(screen.getByLabelText("Пароль")).toBeInTheDocument();
  });

  it("показывает ошибку при неверном пароле", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: "Требуется вход" }, 401))
      .mockResolvedValueOnce(json({ detail: "Неверный логин или пароль" }, 401));
    vi.stubGlobal("fetch", fetchMock);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Логин"), "ivanov");
    await userEvent.type(screen.getByLabelText("Пароль"), "bad");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин или пароль");
  });

  it("после входа рисует боковое меню со всеми разделами", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(USER)));
    renderApp();
    const nav = await screen.findByRole("navigation", { name: "Разделы платформы" });
    for (const name of ["Обзор", "База знаний", "Эксперименты", "Запуск экспериментов", "Методология"]) {
      expect(nav).toContainElement(screen.getByRole("link", { name }));
    }
    expect(screen.getByRole("link", { name: "Обзор" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("img", { name: "Профиль: Иван Иванов" })).toHaveTextContent("ИИ");
  });

  it("открывает пустую страницу раздела", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(USER)));
    renderApp("/methodology");
    expect(await screen.findByRole("heading", { level: 1, name: "Методология" })).toBeInTheDocument();
  });
});
