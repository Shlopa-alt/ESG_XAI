import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ManualMode } from "./components/ManualMode";

describe("Ручной режим", () => {
  it("расчёт: архив с ноутбуком и та же команда в командной строке", () => {
    render(<ManualMode run={57} />);
    expect(screen.getByText("Ручной режим: взять расчёт в свои руки")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Скачать ноутбук Jupyter" })).toHaveAttribute("href", "/api/runs/57/manual.zip");
    expect(screen.getByText("esg notebook --run 57")).toBeInTheDocument();
    expect(screen.getByText(/в реестр результат попадает только из клона репозитория/)).toBeInTheDocument();
  });

  it("версия данных: короткая ссылка в таблице версий", () => {
    render(<ManualMode snapshot={12} compact />);
    expect(screen.getByRole("link", { name: "ноутбук Jupyter" })).toHaveAttribute("href", "/api/snapshots/12/manual.zip");
  });
});
