import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные
const OWNER = { id: 1, login: "[владелец]", full_name: "", email: "", role: "owner", nda_access: true };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("Подключения к базам", () => {
  it("владелец добавляет подключение; пароль уходит на сервер и не показывается", async () => {
    let rows: unknown[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/auth/me") return Promise.resolve(json(OWNER));
      if (url === "/api/studio/connections" && init?.method === "POST") {
        const b = JSON.parse(init.body as string) as Record<string, unknown>;
        rows = [{ code: "DB-01", title: b.title, kind: b.kind, host: b.host, port: b.port, database: b.database, username: b.username, has_password: true, allow_write: false }];
        return Promise.resolve(json(rows[0], 201));
      }
      if (url === "/api/studio/connections") return Promise.resolve(json(rows));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/db-connections"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Подключения к базам" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Название"), "учёт");
    await userEvent.selectOptions(screen.getByLabelText("Тип базы"), "mysql");
    expect(screen.getByLabelText("Порт")).toHaveValue(3306);
    await userEvent.type(screen.getByLabelText("Сервер"), "db.local");
    await userEvent.type(screen.getByLabelText("Пароль"), "секрет-заглушка");
    await userEvent.click(screen.getByRole("button", { name: "Добавить" }));
    const post = fetchMock.mock.calls.find(([u, i]) => u === "/api/studio/connections" && i?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toMatchObject({ kind: "mysql", port: 3306, host: "db.local", password: "секрет-заглушка" });
    expect(await screen.findByRole("cell", { name: "DB-01" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("секрет-заглушка");
  });
});
