import { describe, expect, it } from "vitest";

import { suggestConcepts } from "./ArticlesSummary";

// Названия понятий — из словаря русских названий (concepts.ts), не данные статей
const node = (name: string, documents: number, spellings: string[] = []) => ({ id: name, kind: "сущность", name, documents, spellings });

describe("Подсказка понятий для пункта методики", () => {
  it("русский пункт находит понятие, записанное в статьях по-английски", () => {
    const got = suggestConcepts("Влияние ESG-показателей на стоимость компании", [
      node("firm value", 40),
      node("esg performance", 90),
      node("carbon emissions", 70),
    ]);
    expect(got.map((c) => c.name)).toEqual(["esg performance", "firm value"]);
  });

  it("учитывает варианты написания, пропускает статьи и берёт не больше восьми", () => {
    const many = Array.from({ length: 12 }, (_, i) => node(`[понятие ${i}]`, i, ["[понятие]"]));
    const got = suggestConcepts("[понятие]", [...many, { id: "a", kind: "статья", name: "[понятие]", documents: 999, spellings: [] }]);
    expect(got).toHaveLength(8);
    expect(got[0]).toEqual({ name: "[понятие 11]", documents: 11 });
  });
});
