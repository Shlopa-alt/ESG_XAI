"""Докачка статей через DOAJ, когда исчерпан суточный лимит OpenAlex.

Запросы и направления — те же, что в fetch_more. DOAJ отдаёт не больше 1000 записей на запрос и обычно ссылку
на страницу статьи, поэтому PDF берётся из мета-тега citation_pdf_url этой страницы. Язык определяется по
названию и аннотации: неанглоязычные статьи идут в 12_Non_English/<язык>, англоязычные из неанглийских запросов —
в 00_ESG_general.
"""
import concurrent.futures as cf
import csv
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # запуск через python -I
from fetch_more import DOMAIN, EXTRA, FIELDS, GENERAL, NON_EN, WEIGHT
from fetch_articles import TOPICS, UA, safe_name
from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0
OUT = Path(sys.argv[1])
TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
MANIFEST = OUT / "_список_статей.csv"
CACHE = Path(__file__).parent.parent / "data" / "doaj_candidates.json"
META_PDF = re.compile(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', re.I)
META_PDF2 = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url', re.I)


def api_json(url):
    for i in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 400:                            # за пределами 1000 записей
                return None
        except Exception:
            pass
        time.sleep(5 * (i + 1))
    raise RuntimeError("DOAJ не отвечает: " + url[:150])


def search(query, pages=10):
    q = " AND ".join(f'"{w}"' if not w.isascii() else w for w in query.split()) + " AND bibjson.year:>2017"
    for page in range(1, pages + 1):
        d = api_json(f"https://doaj.org/api/search/articles/{urllib.parse.quote(q)}?pageSize=100&page={page}")
        time.sleep(0.6)
        if not d or not d.get("results"):
            return
        yield from d["results"]
        if page * 100 >= d.get("total", 0):
            return


def to_cand(rec):
    b = rec.get("bibjson", {})
    title, abstract = b.get("title") or "", b.get("abstract") or ""
    links = [l["url"] for l in b.get("link", []) if l.get("url")]
    if not title or not links or not DOMAIN.search((title + " " + abstract + " " + " ".join(b.get("keywords", []))).lower()):
        return None
    try:
        lang = detect(title + ". " + abstract[:500])
    except Exception:
        lang = "xx"
    doi = next((i["id"] for i in b.get("identifier", []) if i.get("type") == "doi"), None)
    a = b.get("author") or [{}]
    return {"id": rec["id"], "doi": f"https://doi.org/{doi.lower()}" if doi else None, "title": title,
            "year": int(b["year"]) if str(b.get("year", "")).isdigit() else None, "cited": 0,
            "language": lang, "author": a[0].get("name", "") or "", "pdfs": links}


def fetch(url, n=60_000_000):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read(n), r.geturl()


def download(c, folder):
    c = dict(c, title=c["title"][:70] + "_" + c["id"][:10])
    dst = folder / safe_name(c)
    if dst.exists() and dst.stat().st_size > 10000:
        return dst
    for u in c["pdfs"]:
        try:
            data, final = fetch(u)
            if data[:5] != b"%PDF-":
                page = data.decode("utf-8", "ignore")
                m = META_PDF.search(page) or META_PDF2.search(page)
                if not m:
                    continue
                data, _ = fetch(urllib.parse.urljoin(final, html.unescape(m.group(1))))
            if data[:5] == b"%PDF-" and len(data) > 20000:
                dst.write_bytes(data)
                return dst
        except Exception:
            continue
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    old = list(csv.DictReader(open(MANIFEST, encoding="utf-8-sig")))
    seen = {(r["doi"] or "").lower() for r in old if r["doi"]}
    seen |= {re.sub(r"\W+", " ", r["title"]).lower().strip() for r in old}
    have_files = {p.name for p in OUT.rglob("*.pdf")}
    need = TOTAL - len(have_files)
    print(f"уже есть {len(have_files)} PDF, докачиваем {need}", flush=True)

    jobs = [(t, q) for t, qs in TOPICS.items() for q in qs + EXTRA.get(t, [])]
    jobs += [("00_ESG_general", q) for q in GENERAL] + [("12_Non_English", q) for q in NON_EN]
    raw = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else []
    done_q = {(t, q) for t, q, _ in raw}
    for t, q in jobs:
        if (t, q) in done_q:
            continue
        cs = [c for c in map(to_cand, search(q)) if c]
        raw.append([t, q, cs])
        CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        print(f"  {t} | {q}: {len(cs)}", flush=True)

    pools = {}
    for t, _, cs in raw:
        for c in cs:
            key = (c["doi"] or "").lower() or re.sub(r"\W+", " ", c["title"]).lower().strip()
            tkey = re.sub(r"\W+", " ", c["title"]).lower().strip()
            if key in seen or tkey in seen:
                continue
            seen |= {key, tkey}
            topic = "12_Non_English" if c["language"] != "en" else ("00_ESG_general" if t == "12_Non_English" else t)
            pools.setdefault(topic, []).append(c)
    for t, p in sorted(pools.items()):
        p.sort(key=lambda c: -(c["year"] or 0))             # цитируемости в DOAJ нет — свежие раньше
        print(f"{t}: {len(p)} новых кандидатов", flush=True)

    order, qs = [], {t: list(p) for t, p in pools.items()}
    while any(qs.values()):
        for t, q in qs.items():
            for _ in range(WEIGHT.get(t, 2)):
                if q:
                    order.append((t, q.pop(0)))

    fh = open(MANIFEST, "a", newline="", encoding="utf-8")
    wr = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
    done, it = 0, iter(order)
    with cf.ThreadPoolExecutor(24) as ex:
        running = {}

        def submit():
            t, c = next(it)
            folder = OUT / t / c["language"] if t == "12_Non_English" else OUT / t
            folder.mkdir(parents=True, exist_ok=True)
            running[ex.submit(download, c, folder)] = (t, c)
        try:
            for _ in range(48):
                submit()
        except StopIteration:
            pass
        while running and done < need:
            fin, _ = cf.wait(running, return_when=cf.FIRST_COMPLETED)
            for f in fin:
                t, c = running.pop(f)
                p = f.result()
                if p and done < need and p.name not in have_files:
                    have_files.add(p.name)
                    done += 1
                    wr.writerow({"topic": t, "file": str(p.relative_to(OUT)), "title": c["title"], "year": c["year"],
                                 "language": c["language"], "doi": c["doi"], "cited_by": ""})
                    if done % 100 == 0:
                        fh.flush()
                        print(f"скачано {done}/{need}", flush=True)
                try:
                    submit()
                except StopIteration:
                    pass
        for f in running:
            f.cancel()
        for f in cf.as_completed([f for f in running if not f.cancelled()]):
            p = f.result()                               # лишние сверх TOTAL — удалить, кроме уже учтённых
            if p and p.name not in have_files:
                p.unlink()
    fh.close()
    print("ИТОГО новых", done, flush=True)


if __name__ == "__main__":
    main()
