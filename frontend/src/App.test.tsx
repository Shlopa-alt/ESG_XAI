import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
    for (const name of ["Обзор", "Методика", "Банк статей", "Идеи для проверки", "Проверки", "Данные"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(nav).getByRole("link", { name: "Обзор" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("img", { name: "Профиль: Иван Иванов" })).toHaveTextContent("ИИ");
  });

  it("«Забыли пароль?» отправляет логин и показывает ответ сервера", async () => {
    const sent = "Если такой пользователь есть и у него указана почта, письмо со ссылкой уже отправлено.";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: "Требуется вход" }, 401))
      .mockResolvedValueOnce(json({ detail: sent }));
    vi.stubGlobal("fetch", fetchMock);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Логин"), "ivanov");
    await userEvent.click(screen.getByRole("button", { name: "Забыли пароль?" }));
    expect(screen.getByLabelText("Логин или почта")).toHaveValue("ivanov");
    await userEvent.click(screen.getByRole("button", { name: "Прислать ссылку" }));
    expect(await screen.findByRole("status")).toHaveTextContent(sent);
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/auth/forgot");
    expect(JSON.parse(init.body as string)).toEqual({ login: "ivanov" });
    await userEvent.click(screen.getByRole("button", { name: "Вернуться ко входу" }));
    expect(screen.getByRole("button", { name: "Войти" })).toBeInTheDocument();
  });

  it("по ссылке из письма задаёт новый пароль и входит", async () => {
    window.location.hash = "#tok-123";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ detail: "Требуется вход" }, 401))
      .mockResolvedValue(json(USER));
    vi.stubGlobal("fetch", fetchMock);
    renderApp("/reset-password");
    await userEvent.type(await screen.findByLabelText("Новый пароль"), "new-pass-456");
    await userEvent.type(screen.getByLabelText("Новый пароль ещё раз"), "new-pass-456");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить и войти" }));
    expect(await screen.findByRole("navigation", { name: "Разделы платформы" })).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/auth/reset");
    expect(JSON.parse(init.body as string)).toEqual({ token: "tok-123", new_password: "new-pass-456" });
    window.location.hash = "";
  });

  it("открывает пустую страницу раздела", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(USER)));
    renderApp("/methodology");
    expect(await screen.findByRole("heading", { level: 1, name: "Методика" })).toBeInTheDocument();
  });
});
