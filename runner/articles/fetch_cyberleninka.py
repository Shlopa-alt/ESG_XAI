"""Русскоязычные статьи с КиберЛенинки по направлениям лаборатории → 13_Russian_CL/<направление>.

Поиск — POST /api/search (не больше 1000 записей на запрос), PDF — /article/n/<slug>/pdf. Сайт за Cloudflare,
поэтому качаем в несколько потоков с паузами. Манифест общей папки дописывается.
"""
import concurrent.futures as cf
import csv
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(sys.argv[1])
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
ROOT = "13_Russian_CL"
MANIFEST = OUT / "_articles_list.csv"
FIELDS = ["topic", "file", "title", "year", "language", "doi", "cited_by"]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
# Кэш — не во временной папке: её чистит Windows
CACHE = Path.home() / "ESG_data" / "cache" / "cyberleninka_candidates.json"

# Короткие имена папок архива (длинные пути не открывал Проводник)
FOLDER = {"01_ESG_financial_performance": "01_ESG_finance", "02_AI_XAI_ESG": "02_AI_XAI",
          "04_Decision_support_investment": "04_Investment", "06_Reporting_greenwashing": "06_Reporting",
          "07_Monitoring_emissions": "07_Emissions", "09_Project_valuation_behavioral": "09_Valuation",
          "11_ESG_Russia_regions": "11_Regions"}

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))


def translit(s):
    return "".join(_TR.get(ch.lower(), ch) for ch in s)

TOPICS = {
    "01_ESG_financial_performance": ["ESG финансовые результаты", "ESG рентабельность", "ESG стоимость компании",
                                     "нефинансовые факторы финансовые показатели", "машинное обучение ESG"],
    "02_AI_XAI_ESG": ["искусственный интеллект ESG", "объяснимый искусственный интеллект",
                      "интерпретируемость машинного обучения финансы", "нейронные сети устойчивое развитие"],
    "03_Causal_ESG": ["влияние ESG на эффективность компании", "эконометрический анализ ESG",
                      "влияние устойчивого развития на финансовые показатели"],
    "04_Decision_support_investment": ["ESG инвестиции", "ответственное инвестирование", "зеленые облигации",
                                       "поддержка принятия решений устойчивое развитие", "ESG портфель"],
    "05_ESG_ratings": ["ESG-рейтинг", "рейтинговые агентства ESG", "оценка ESG методика"],
    "06_Reporting_greenwashing": ["нефинансовая отчетность", "гринвошинг", "отчет об устойчивом развитии"],
    "07_Monitoring_emissions": ["углеродный след компании", "мониторинг выбросов парниковых газов предприятие",
                                "цифровой двойник устойчивое развитие"],
    "08_Knowledge_graph": ["граф знаний устойчивое развитие", "графовые нейронные сети финансы"],
    "09_Project_valuation_behavioral": ["оценка инвестиционных проектов ESG", "чистый дисконтированный доход нейронная сеть",
                                        "поведенческие финансы инвестиционные решения", "нейронные сети управление бизнесом"],
    "10_CSR_SDG": ["корпоративная социальная ответственность", "цели устойчивого развития компании",
                   "социальные инвестиции бизнеса"],
    "11_ESG_Russia_regions": ["ESG-трансформация", "ESG Россия", "устойчивое развитие российских компаний",
                              "особые экономические зоны устойчивое развитие", "ESG регион"],
}
DOMAIN = re.compile(r"esg|устойчив|нефинансов|социальн|экологич|углерод|зелен|зелён|климат|ответствен|"
                    r"инвест|финанс|компан|предприят|бизнес|корпоратив")


def post(q, start):
    body = json.dumps({"mode": "articles", "q": q, "size": 100, "from": start}).encode()
    for i in range(6):
        try:
            req = urllib.request.Request("https://cyberleninka.ru/api/search", data=body,
                                         headers={**UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            time.sleep(5 * (i + 1))
    raise RuntimeError("КиберЛенинка не отвечает: " + q)


def clean(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def search(q):
    for start in range(0, 1000, 100):
        d = post(q, start)
        time.sleep(1)
        arts = d.get("articles") or []
        for a in arts:
            title = clean(a.get("name"))
            if (a.get("year") or 0) >= 2018 and title and DOMAIN.search((title + " " + clean(a.get("annotation"))).lower()):
                yield {"link": a["link"], "title": title, "year": a.get("year"),
                       "author": (a.get("authors") or [""])[0], "journal": a.get("journal", "")}
        if len(arts) < 100 or start + 100 >= d.get("found", 0):
            return


def safe_name(c):
    # Только латиница и короткая длина — архив открывается встроенным zip Windows
    a = re.sub(r"[^A-Za-z0-9]+", "", translit((c["author"].split() or ["NA"])[0]))[:20] or "NA"
    t = re.sub(r"[^A-Za-z0-9_-]+", "_", translit(c["title"])).strip("_")[:45].rstrip("_")
    return f"{c['year']}_{a.lower()}_{t.lower()}.pdf"


def download(c, folder):
    # при блокировке (429/403/503 или HTML-страница вместо PDF) ждём и повторяем, а не пропускаем статью
    dst = folder / safe_name(c)
    if dst.exists() and dst.stat().st_size > 10000:
        return dst
    for i in range(12):
        try:
            req = urllib.request.Request("https://cyberleninka.ru" + c["link"] + "/pdf", headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read(80_000_000)
            if data[:5] == b"%PDF-" and len(data) > 10000:
                dst.write_bytes(data)
                time.sleep(1.5)
                return dst
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
        time.sleep(min(30 * (i + 1), 300))
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    raw = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else []
    done_q = {(t, q) for t, q, _ in raw}
    for t, qs in TOPICS.items():
        for q in qs:
            if (t, q) not in done_q:
                cs = list(search(q))
                raw.append([t, q, cs])
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
                print(f"  {t} | {q}: {len(cs)}", flush=True)
    seen, pools = set(), {}
    for t, _, cs in raw:
        for c in cs:
            if c["link"] not in seen:
                seen.add(c["link"])
                pools.setdefault(t, []).append(c)
    for t, p in pools.items():
        print(f"{t}: {len(p)} кандидатов", flush=True)

    order, qs = [], {t: list(p) for t, p in pools.items()}
    while any(qs.values()):
        for t, q in qs.items():
            if q:
                order.append((t, q.pop(0)))

    have = {r["doi"] for r in csv.DictReader(open(MANIFEST, encoding="utf-8-sig")) if r["topic"].startswith(ROOT)}
    order = [(t, c) for t, c in order if "https://cyberleninka.ru" + c["link"] not in have]
    target = TARGET - len(have)
    print(f"уже есть {len(have)}, докачиваем {target}", flush=True)
    fh = open(MANIFEST, "a", newline="", encoding="utf-8")
    wr = csv.DictWriter(fh, fieldnames=FIELDS)
    done, it = 0, iter(order)
    with cf.ThreadPoolExecutor(3) as ex:
        running = {}

        def submit():
            t, c = next(it)
            folder = OUT / ROOT / FOLDER.get(t, t)
            folder.mkdir(parents=True, exist_ok=True)
            running[ex.submit(download, c, folder)] = (t, c)
        try:
            for _ in range(4):
                submit()
        except StopIteration:
            pass
        while running and done < target:
            fin, _ = cf.wait(running, return_when=cf.FIRST_COMPLETED)
            for f in fin:
                t, c = running.pop(f)
                p = f.result()
                if p and done < target:
                    done += 1
                    wr.writerow({"topic": f"{ROOT}/{FOLDER.get(t, t)}", "file": p.relative_to(OUT).as_posix(), "title": c["title"],
                                 "year": c["year"], "language": "ru", "doi": "https://cyberleninka.ru" + c["link"],
                                 "cited_by": ""})
                    if done % 100 == 0:
                        fh.flush()
                        print(f"скачано {done}/{target}", flush=True)
                try:
                    submit()
                except StopIteration:
                    pass
        for f in running:
            f.cancel()
        for f in cf.as_completed([f for f in running if not f.cancelled()]):
            p = f.result()
            if p:
                p.unlink()
    fh.close()
    print("ИТОГО", done, flush=True)


if __name__ == "__main__":
    main()
