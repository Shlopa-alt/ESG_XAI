import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComponentSchema } from "./api/studio";
import { App } from "./App";
import { StudioChart, StudioQuality, StudioReport } from "./components/StudioCharts";
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

describe("Студия: визуализаторы", () => {
  const view = {
    table: { columns: [{ name: "x", kind: "number" }, { name: "y", kind: "number" }, { name: "s", kind: "string" }], rows: [[1, 2, "a"], [2, 4, "a"], [3, 7, "b"]], total: 3 },
    statistics: { rows: 3, columns: [{ name: "x", kind: "number", count: 3, missing: 0, unique: 3, histogram: [{ from: 1, to: 2, count: 2 }, { from: 2, to: 3, count: 1 }] }] },
    quality: { rows: 3, duplicate_rows: 1, issues: 2, columns: [{ name: "s", kind: "string", missing: 0, missing_share: 0, unique: 2, problems: ["числа записаны текстом (100%)"] }] },
  };

  it("«Качество данных» перечисляет замечания", () => {
    wrap(<StudioQuality view={view} />);
    expect(screen.getByText(/Замечаний: 2/)).toHaveTextContent("повторяющихся строк: 1");
    expect(screen.getByText("числа записаны текстом (100%)")).toBeInTheDocument();
  });

  it("«Диаграмма»: гистограмма по всем строкам, точки по выборке", async () => {
    wrap(<StudioChart view={view} />);
    expect(screen.getByRole("img", { name: "Гистограмма «x» по всем строкам" }).querySelectorAll("rect")).toHaveLength(2);
    await userEvent.selectOptions(screen.getByLabelText("Вид"), "scatter");
    await userEvent.selectOptions(screen.getByLabelText("Ось Y"), "y");
    expect(screen.getByRole("img", { name: "Точки: «x» и «y»" }).querySelectorAll("circle")).toHaveLength(3);
    await userEvent.selectOptions(screen.getByLabelText("Вид"), "bar");
    await userEvent.selectOptions(screen.getByLabelText("Столбец"), "s");
    expect(screen.getByRole("img", { name: "Частота значений «s»" }).querySelectorAll("rect")).toHaveLength(2);
  });
});

describe("Студия: отчёт модели", () => {
  it("показывает метрики по множествам, коэффициенты и ROC", () => {
    wrap(
      <StudioReport
        report={{
          kind: "classification",
          title: "[модель]",
          metrics: [{ name: "AUC", train: 0.9, test: 0.8, cv: null }],
          summary: [["[сводка]", 3]],
          tables: [{ title: "Коэффициенты", columns: ["признак", "коэффициент"], rows: [["[x]", 1.5]] }],
          roc: [{ fpr: 0, tpr: 0 }, { fpr: 0.2, tpr: 0.7 }, { fpr: 1, tpr: 1 }],
        }}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Тестовое" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Кросс-валидация" })).not.toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1,5" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "ROC-кривая" })).toBeInTheDocument();
  });
});
