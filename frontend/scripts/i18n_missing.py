"""Какие русские подписи интерфейса ещё не переведены в src/i18n/en.ts (английская версия, п. 3 фидбека).

    python frontend/scripts/i18n_missing.py

Проходит src/**/*.ts(x) (без тестов): текст JSX, строки и шаблоны `…${}…` с кириллицей, без комментариев.
Печатает то, чего нет в словаре: эти строки добавить в EN.exact (шаблоны с числами — в EN.templates,
части ${} — {0}, {1}…). Данные и тексты с сервера сюда не попадают — их и не нужно переводить.
"""

import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
CYR = re.compile(r"[А-Яа-яЁё]")


def norm(s: str) -> str:
    return " ".join(s.split())


def scan(src: str) -> tuple[list[str], list[list[str]], str]:
    """Строки, шаблоны (части между ${}), код без строк и комментариев (строки заменены на пробелы)."""
    strings, templates, code = [], [], []
    i, n = 0, len(src)
    stack: list[str] = []  # "tpl" — внутри шаблона, "expr" — внутри ${ } (с глубиной скобок)
    depth: list[int] = []
    parts: list[list[str]] = []
    while i < n:
        c = src[i]
        if stack and stack[-1] == "tpl":
            if c == "\\":
                parts[-1][-1] += src[i:i + 2]
                i += 2
                continue
            if c == "`":
                templates.append(parts.pop())
                stack.pop()
                code.append(" ")
                i += 1
                continue
            if src.startswith("${", i):
                stack.append("expr")
                depth.append(0)
                parts[-1].append("")
                i += 2
                continue
            parts[-1][-1] += c
            i += 1
            continue
        # код (в том числе внутри ${ })
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "'\"":
            j = i + 1
            buf = ""
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\":
                    buf += src[j + 1] if j + 1 < n else ""
                    j += 2
                    continue
                buf += src[j]
                j += 1
            strings.append(buf)
            code.append(" ")
            i = j + 1
            continue
        if c == "`":
            stack.append("tpl")
            parts.append([""])
            i += 1
            continue
        if stack and stack[-1] == "expr":
            if c == "{":
                depth[-1] += 1
            elif c == "}":
                if depth[-1] == 0:
                    stack.pop()
                    depth.pop()
                    parts[-1].append("")
                    i += 1
                    continue
                depth[-1] -= 1
            i += 1
            continue
        code.append(c)
        i += 1
    return strings, templates, "".join(code)



def main() -> int:
    text = (SRC / "i18n" / "en.ts").read_text(encoding="utf-8")
    d = json.loads(text[text.index("= {") + 2: text.rindex(";")])
    have = {norm(k) for k in d["exact"]} | {k.lower() for k in map(norm, d["exact"])}
    tpls = {norm(k) for k in d["templates"]}
    missing: list[str] = []
    for f in sorted(SRC.rglob("*.ts*")):
        if ".test." in f.name or f.parent.name == "i18n" or f.name in ("concepts.ts", "test-setup.ts", "LangSwitch.tsx"):
            continue
        strings, templates, code = scan(f.read_text(encoding="utf-8"))
        found = [norm(s) for s in strings if CYR.search(s)]
        found += [norm(m.group(0)) for m in re.finditer(r"[^<>{}]*[А-Яа-яЁё][^<>{}]*", code)]
        for s in found:
            if s and s not in have and s.lower() not in have and not re.search(r"\.match\(|\.replace\(|/g\b", s):  # регулярные выражения в коде
                missing.append(f"{f.relative_to(SRC)}: {s}")
        for t in templates:
            parts = [t[k] for k in range(0, len(t), 2)]
            key = norm("".join(p + (f"{{{i}}}" if i < len(parts) - 1 else "") for i, p in enumerate(parts)))
            if CYR.search(key) and key not in tpls and len(parts) > 1:
                missing.append(f"{f.relative_to(SRC)}: (шаблон) {key}")
    for m in sorted(set(missing)):
        print(m)
    print(f"Не переведено: {len(set(missing))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
