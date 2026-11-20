import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const USER = { id: 1, login: "ivanov", full_name: "Иван Иванов", email: "", role: "researcher", nda_access: false };
const ROW = {
  id: 7,
  login: "ivanov",
  name: "скрипт выгрузки",
  prefix: "esg_abcdefgh",
  scope: "read",
  created_at: "2026-11-20T10:00:00Z",
  expires_at: "2027-02-18T10:00:00Z",
  last_used_at: null,
  revoked_at: null,
  active: true,
};

function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("Доступ к API", () => {
  it("создаёт токен, показывает его один раз и отзывает", async () => {
    let rows: unknown[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/auth/me") return Promise.resolve(json(USER));
      if (url === "/api/tokens" && init?.method === "POST") {
        rows = [ROW];
        return Promise.resolve(json({ ...ROW, token: "esg_abcdefgh-secret" }, 201));
      }
      if (url === "/api/tokens/7" && init?.method === "DELETE") {
        rows = [{ ...ROW, active: false, revoked_at: "2026-11-20T11:00:00Z" }];
        return Promise.resolve(json(null, 204));
      }
      if (url.startsWith("/api/tokens")) return Promise.resolve(json(rows));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/api-access"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Доступ к API" })).toBeInTheDocument();
    expect(screen.getByText("Токенов пока нет.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Название"), "скрипт выгрузки");
    await userEvent.selectOptions(screen.getByLabelText("Права"), "write");
    await userEvent.click(screen.getByRole("button", { name: "Создать токен" }));
    expect(await screen.findByText("esg_abcdefgh-secret")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([u, i]) => u === "/api/tokens" && i?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ name: "скрипт выгрузки", scope: "write", days: 90 });

    await userEvent.click(screen.getByRole("button", { name: "Сохранил, закрыть" }));
    expect(screen.queryByText("esg_abcdefgh-secret")).not.toBeInTheDocument();
    const row = (await screen.findByText("скрипт выгрузки", { selector: "td" })).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Отозвать" }));
    await userEvent.click(within(row).getByRole("button", { name: "Да, отозвать" }));
    expect(await within(row).findByText("отозван")).toBeInTheDocument();
  });
});
