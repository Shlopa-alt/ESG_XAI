// Текст фрагмента статьи: таблицы, которые docling оставляет во фрагменте разметкой, показываются таблицей.
// Два вида разметки:
// - markdown: строки «| a | b |» со строкой-разделителем «|---|---|»;
// - пары «строка, столбец = значение. …» (так docling пишет таблицу в текст фрагмента).
// Всё, что не похоже на таблицу, остаётся обычным текстом с переносами строк.

export type Block = { kind: "text"; text: string } | { kind: "table"; head: string[]; rows: string[][] };

const PIPE_ROW = /^\s*\|.*\|\s*$/;
const PIPE_RULE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
// «строка, столбец = значение»: строка — до первой запятой, значение — до «. » перед следующей парой или до конца
const TRIPLE = /([^=,.]+?), ([^=]+?) = ([^=]*?)(?:\.\s+(?=[^=,.]+?, [^=]+? = )|\.?\s*$)/gy;
const MIN_TRIPLES = 4;
// число в ячейке: «0,12», «1 200», «−2,7», «18 %» — выравнивается вправо, как в остальных таблицах
const NUMERIC = /^[-−+]?\d[\d\s]*([.,]\d+)?\s*%?$/; // \s в JS включает и неразрывный пробел

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function pipeTable(lines: string[]): Block {
  const [first = "", , ...rest] = lines;
  const parsed = rest.map(cells);
  // ячейки сверх заголовка не отбрасываем: заголовок дополняется пустыми столбцами
  const cols = Math.max(cells(first).length, ...parsed.map((r) => r.length));
  const pad = (r: string[]) => (r.length < cols ? [...r, ...Array<string>(cols - r.length).fill("")] : r);
  return { kind: "table", head: pad(cells(first)), rows: parsed.map(pad) };
}

/** Абзац из одних пар «строка, столбец = значение» → таблица; иначе null. */
export function tripleTable(text: string): Block | null {
  const s = text.trim();
  TRIPLE.lastIndex = 0;
  const found: Array<[string, string, string]> = [];
  let m: RegExpExecArray | null;
  while (TRIPLE.lastIndex < s.length && (m = TRIPLE.exec(s)) !== null) {
    found.push([(m[1] ?? "").trim(), (m[2] ?? "").trim(), (m[3] ?? "").trim()]);
  }
  if (TRIPLE.lastIndex !== s.length || found.length < MIN_TRIPLES) return null;
  const rowKeys = [...new Set(found.map((t) => t[0]))];
  const colKeys = [...new Set(found.map((t) => t[1]))];
  // пары должны складываться в сетку: иначе это перечисление в тексте, а не таблица
  if (rowKeys.length < 2 || colKeys.length < 2) return null;
  const grid = new Map<string, string>();
  for (const [r, c, v] of found) {
    const key = `${r}\u0000${c}`;
    // одна ячейка с разными значениями — не таблица: оставляем текст, чтобы не потерять число
    if (grid.has(key) && grid.get(key) !== v) return null;
    grid.set(key, v);
  }
  return {
    kind: "table",
    head: ["", ...colKeys],
    rows: rowKeys.map((r) => [r, ...colKeys.map((c) => grid.get(`${r}\u0000${c}`) ?? "")]),
  };
}

export function splitBlocks(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let buf: string[] = [];
  const flush = () => {
    const joined = buf.join("\n").trim();
    buf = [];
    if (!joined) return;
    for (const para of joined.split(/\n{2,}/)) {
      blocks.push(tripleTable(para) ?? { kind: "text", text: para.trim() });
    }
  };
  for (let i = 0; i < lines.length; ) {
    const line = lines[i] ?? "";
    if (PIPE_ROW.test(line) && PIPE_RULE.test(lines[i + 1] ?? "")) {
      let j = i + 2;
      while (j < lines.length && PIPE_ROW.test(lines[j] ?? "")) j++;
      flush();
      blocks.push(pipeTable(lines.slice(i, j)));
      i = j;
    } else {
      buf.push(line);
      i++;
    }
  }
  flush();
  return blocks;
}

export function FragmentText({ text }: { text: string }) {
  return (
    <>
      {splitBlocks(text).map((b, i) =>
        b.kind === "text" ? (
          <p key={i} className="fragment-text">
            {b.text}
          </p>
        ) : (
          <div key={i} className="table-wrap fragment-table">
            <table className="table">
              {b.head.some(Boolean) && (
                <thead>
                  <tr>
                    {b.head.map((h, j) => (
                      <th key={j} scope="col">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
              )}
              <tbody>
                {b.rows.map((r, j) => (
                  <tr key={j}>
                    {r.map((c, k) => (
                      <td key={k} className={NUMERIC.test(c) ? "num" : undefined}>
                        {c}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ),
      )}
    </>
  );
}
