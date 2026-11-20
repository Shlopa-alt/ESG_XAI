import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComponentSchema } from "./api/studio";
import { App } from "./App";
import { StudioParams } from "./components/StudioParams";

// Заглушки — не реальные данные
const USER = { id: 1, login: "[логин]", full_name: "", email: "", role: "researcher", nda_access: false };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

function wrap(ui: React.ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Студия: список", () => {
  it("показывает сценарии и создаёт новый", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/auth/me") return Promise.resolve(json(USER));
      if (url === "/api/studio/scenarios" && init?.method === "POST")
        return Promise.resolve(json({ code: "SC-02", title: "[новый]", description: "", version: 1, author: "[логин]", nodes: 0, updated_at: "2026-11-20T10:00:00Z" }, 201));
      if (url === "/api/studio/scenarios")
        return Promise.resolve(json([{ code: "SC-01", title: "[сценарий]", description: "", version: 3, author: "[автор]", nodes: 4, updated_at: "2026-11-20T10:00:00Z" }]));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    wrap(<App />, "/studio");
    expect(await screen.findByRole("heading", { level: 1, name: "Студия анализа" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "[сценарий]" })).toHaveAttribute("href", "/studio/SC-01");
    await userEvent.type(screen.getByLabelText("Название"), "новый");
    await userEvent.click(screen.getByRole("button", { name: "Создать" }));
    const post = fetchMock.mock.calls.find(([u, i]) => u === "/api/studio/scenarios" && i?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ title: "новый", description: "" });
  });
});

const GROUP: ComponentSchema = {
  type: "transform.group",
  title: "Группировка",
  group: "Трансформация",
  description: "",
  inputs: [{ name: "in", label: "Вход" }],
  params: [
    { name: "keys", label: "Поля группы", kind: "columns", required: false, from_port: "in" },
    {
      name: "aggregations",
      label: "Вычисления",
      kind: "rows",
      required: true,
      fields: [
        { name: "column", label: "Столбец", kind: "column", required: true, from_port: "in" },
        { name: "func", label: "Функция", kind: "select", required: true, options: [{ value: "sum", label: "сумма" }, { value: "mean", label: "среднее" }] },
      ],
    },
  ],
};

function Harness({ columns, onValues }: { columns: string[]; onValues: (v: Record<string, unknown>) => void }) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  return (
    <StudioParams
      comp={GROUP}
      values={values}
      columns={() => columns}
      onChange={(v) => {
        setValues(v);
        onValues(v);
      }}
    />
  );
}

describe("Студия: настройки узла", () => {
  it("строит поля по схеме: столбцы входа — списком, строки вычислений добавляются", async () => {
    const seen = vi.fn();
    wrap(<Harness columns={["[отрасль]", "[выручка]"]} onValues={seen} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "[отрасль]" }));
    await userEvent.click(screen.getByRole("button", { name: "Добавить" }));
    await userEvent.selectOptions(screen.getByLabelText("Столбец *"), "[выручка]");
    await userEvent.selectOptions(screen.getByLabelText("Функция *"), "mean");
    expect(seen).toHaveBeenLastCalledWith({ keys: ["[отрасль]"], aggregations: [{ column: "[выручка]", func: "mean" }] });
  });

  it("без известных столбцов — ввод через запятую", async () => {
    const seen = vi.fn();
    wrap(<Harness columns={[]} onValues={seen} />);
    await userEvent.type(screen.getByLabelText("Поля группы"), "a, b");
    expect(seen).toHaveBeenLastCalledWith({ keys: ["a", "b"] });
    expect(screen.getByLabelText("Поля группы")).toHaveValue("a, b");
  });
});
