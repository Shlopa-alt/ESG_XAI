import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { BarChart, RangeChart } from "./Charts";

// Заглушки — не реальные данные: проверяется только доступ к значениям с клавиатуры
describe("Графики отчёта с клавиатуры", () => {
  it("столбец — кнопка: Tab доводит до него и показывает значение", async () => {
    render(<BarChart spec={{ id: "b", kind: "bars", title: "[график]", unit: "", categories: ["[a]"], series: [{ name: "[серия]", values: [2] }] }} />);
    const bar = screen.getByRole("button", { name: "[a], [серия]: 2" });
    await userEvent.tab(); // сначала переключатель «таблицей»
    await userEvent.tab(); // затем «Скачать CSV»
    await userEvent.tab();
    expect(bar).toHaveFocus();
    expect(screen.getByText("2", { selector: ".viz-tip strong" })).toBeInTheDocument();
  });

  it("точка диапазона — кнопка с подписью среднего и границ", () => {
    render(<RangeChart spec={{ id: "r", kind: "ranges", title: "[график]", unit: "", rows: [{ name: "[r]", mean: 1, min: 0, max: 3 }] }} />);
    expect(screen.getByRole("button", { name: "[r]: среднее 1, от 0 до 3" })).toBeInTheDocument();
  });
});
