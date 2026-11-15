import { describe, expect, it } from "vitest";

import { chartCsv } from "./components/Charts";

// Выгрузка для своих инструментов эксперта: CSV графика отчёта. Числа — заглушки.
describe("CSV графика", () => {
  it("столбцы: категории × серии, «;», десятичная запятая, метка UTF-8; пустые значения — пусто", () => {
    const csv = chartCsv({
      id: "r2", kind: "bars", title: "[график]", unit: "", categories: ["[a; b]", "[c]"],
      series: [{ name: "[ряд 1]", values: [0.5, Number.NaN] }, { name: "[ряд \"2\"]", values: [-1.25, 3] }],
    });
    expect(csv.startsWith("\ufeff")).toBe(true);
    expect(csv.slice(1).split("\r\n")).toEqual([
      'Категория;[ряд 1];"[ряд ""2""]"',
      '"[a; b]";0,5;-1,25',
      "[c];;3",
      "",
    ]);
  });

  it("диапазоны: среднее, минимум, максимум", () => {
    const csv = chartCsv({ id: "s", kind: "ranges", title: "[г]", unit: "R²", rows: [{ name: "[модель]", mean: 0.6, min: 0.4, max: 0.7 }] });
    expect(csv.slice(1).split("\r\n").slice(0, 2)).toEqual(["Строка;Среднее;Минимум;Максимум", "[модель];0,6;0,4;0,7"]);
  });
});
