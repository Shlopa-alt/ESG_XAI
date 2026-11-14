import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FragmentText, splitBlocks, tripleTable } from "./FragmentText";

// Заглушки — не реальные данные: проверяется только разбор разметки
describe("Таблица во фрагменте статьи", () => {
  it("markdown-таблица показывается таблицей, текст вокруг — абзацами", () => {
    const text = ["[текст до]", "| [столбец 1] | [столбец 2] |", "|---|---:|", "| [a] | [1] |", "| [b] | [2] |", "[текст после]"].join("\n");
    render(<FragmentText text={text} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["[столбец 1]", "[столбец 2]"]);
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("[текст до]")).toBeInTheDocument();
    expect(screen.getByText("[текст после]")).toBeInTheDocument();
    expect(screen.queryByText(/\|/)).not.toBeInTheDocument();
  });

  it("пары «строка, столбец = значение» складываются в сетку", () => {
    const b = tripleTable("[r1], [c1] = 0.27. [r1], [c2] = -0.02. [r2], [c1] = 1,5. [r2], [c2] = 3.");
    expect(b).toEqual({
      kind: "table",
      head: ["", "[c1]", "[c2]"],
      rows: [
        ["[r1]", "0.27", "-0.02"],
        ["[r2]", "1,5", "3"],
      ],
    });
  });

  it("обычный текст с запятыми и знаком равенства таблицей не становится", () => {
    expect(tripleTable("[слово], [слово] = [слово]. [другой текст без пар].")).toBeNull();
    expect(splitBlocks("[абзац 1]\n\n[абзац 2]")).toEqual([
      { kind: "text", text: "[абзац 1]" },
      { kind: "text", text: "[абзац 2]" },
    ]);
  });

  it("строки с «|» без строки-разделителя остаются текстом", () => {
    expect(splitBlocks("| [не таблица] |")).toEqual([{ kind: "text", text: "| [не таблица] |" }]);
  });
});
