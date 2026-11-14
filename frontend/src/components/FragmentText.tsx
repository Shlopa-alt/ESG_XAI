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
  const head = cells(first);
  const cols = head.length;
  const rows = rest.map((l) => {
    const r = cells(l).slice(0, cols);
    return r.length < cols ? [...r, ...Array<string>(cols - r.length).fill("")] : r;
  });
  return { kind: "table", head, rows };
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
  const grid = new Map(found.map(([r, c, v]) => [`${r}\u0000${c}`, v]));
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
                      <td key={k}>{c}</td>
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
