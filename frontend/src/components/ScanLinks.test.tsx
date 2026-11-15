import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Hypotheses } from "../pages/HypothesesPage";
import type { RunRow } from "../pages/RunPage";
import { ideaDraft, ScanLinks } from "./ScanLinks";

// Заглушки — не реальные данные: проверяется только поведение блока найденных связей
const link = (a: string, b: string, kind: string, rho: number, rho_confirm: number | null) => ({
  a, b, kind, rho, xi: 0.5, rho_confirm, xi_confirm: 0.4, n: 200,
});
const RUN = {
  id: 7, experiment: "EXP-010", status: "done", template: "correlation-scan", dataset: "DS-03", snapshot_id: 12,
  summary: {
    links: [link("[x]", "[y]", "монотонная", -0.55, -0.52), link("[x]", "[u]", "немонотонная", 0.01, 0.02)],
    not_confirmed: [link("[n1]", "[n2]", "немонотонная", -0.07, 0.01)],
  },
} as unknown as RunRow;

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("Найденные связи на странице расчёта", () => {
  it("подтверждённые — с переходом к сетям и к идее, не подтвердившиеся — отдельно", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(json(url.includes("/auth/me") ? { id: 1, login: "[логин]", role: "reader", nda_access: false } : [])),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/run"]}>
          <Routes>
            <Route path="/run" element={<ScanLinks run={RUN} />} />
            <Route path="/hypotheses" element={<Hypotheses />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("link", { name: "Предсказать «[y]» нейросетями по остальным столбцам" })).toHaveAttribute(
      "href",
      `/analysis?snapshot=12&target=${encodeURIComponent("[y]")}`,
    );
    expect(screen.getByText(/Не подтвердились на отложенной части · 1/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Предложить идеей" })[0] as HTMLElement);
    // форма идеи открыта и заполнена черновиком: человек допишет и решит, отправлять ли
    expect(await screen.findByLabelText("Коротко, о чём идея")).toHaveValue("Связь «[x]» и «[y]» сохраняется на других данных");
    expect(screen.getByLabelText("Проверяемое утверждение")).toHaveValue(
      "Чем больше «[x]», тем меньше «[y]» — и это сохраняется на других данных.",
    );
    expect((screen.getByLabelText("Обоснование") as HTMLTextAreaElement).value).toMatch(/EXP-010, DS-03, расчёт № 7.*не причина/);
  });

  it("немонотонная связь — без «больше / меньше»; без подтверждённых — так и сказано", () => {
    const d = ideaDraft(link("[x]", "[u]", "немонотонная", 0.01, 0.02), RUN);
    expect(d.statement).toMatch(/немонотонно/);
    expect(d.rationale).toMatch(/ξ Чаттерджи/);
    render(
      <MemoryRouter>
        <ScanLinks
          run={{
            ...RUN,
            summary: {
              links: [], not_confirmed: [{ ...link("[n1]", "[n2]", "немонотонная", -0.07, null), reason: "no_data" }],
              rows_confirm: 30, same_pairs: [{ a: "[ROA 2021]", b: "[ROA 2022]", rho: 0.99 }],
            },
          }}
        />
      </MemoryRouter>,
    );
    // «не нашли» — не «доказали, что нет»; неподтверждённые видны сразу, с причиной; немонотонная — по ξ
    expect(screen.getByText(/Ни одна связь не подтвердилась на отложенной части \(30 строк\).*не доказывает, что их нет/)).toBeInTheDocument();
    expect(screen.queryByText(/Каждая связь подтвердилась/)).not.toBeInTheDocument();
    expect(screen.getByText(/Не подтвердились на отложенной части · 1/).closest("details")).toHaveAttribute("open");
    expect(screen.getByText(/ξ на части поиска 0,5/)).toBeInTheDocument();
    expect(screen.getByText(/не хватило строк/)).toBeInTheDocument();
    expect(screen.getByText(/Почти совпадают.*«\[ROA 2021\]» и «\[ROA 2022\]»/)).toBeInTheDocument();
  });
});
