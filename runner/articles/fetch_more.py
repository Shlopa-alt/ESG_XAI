"""Докачивает статьи к уже собранной папке до TOTAL файлов: все страницы выдачи OpenAlex + неанглоязычные статьи.

Английские запросы берутся из fetch_articles.TOPICS (все страницы, а не первые 200) с фильтром по предметным словам
в названии/аннотации — широкие запросы иначе тянут медицину и энергетику. Неанглоязычные статьи идут в папку
12_Non_English/<язык>. Уже скачанные (по DOI/OpenAlex id из манифеста) пропускаются, манифест дописывается по ходу.
"""
import concurrent.futures as cf
import csv
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # запуск через python -I
from fetch_articles import TOPICS, UA, download, get_json, safe_name

OUT = Path(sys.argv[1])
TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
MAX_PAGES = 5                                        # до 1000 результатов на запрос
MANIFEST = OUT / "_список_статей.csv"
FIELDS = ["topic", "file", "title", "year", "language", "doi", "cited_by"]

DOMAIN = re.compile(
    r"esg|sustainab|csr|corporate social|social responsib|green|climat|carbon|emission|environmental|governance|"
    r"impact invest|sdg|responsible invest|устойчив|сталого|сталий|нефинансов|ксо|sustent|sosten|nachhalt|durable|"
    r"rse|keberlanjutan|sürdürülebilir|可持续|环境|持続可能|ความยั่งยืน|kestävä|fenntarth|zrównoważ")

# неанглоязычный блок: ESG + «устойчивое развитие / КСО / нефинансовая отчётность» на основных языках выдачи
NON_EN = ["ESG", "ESG performance", "ESG rating", "environmental social governance",
          "устойчивое развитие компании", "ESG-трансформация", "нефинансовая отчетность", "корпоративная социальная ответственность",
          "сталий розвиток підприємства", "ESG-звітність",
          "sustentabilidade empresarial", "desempenho ESG", "responsabilidade social corporativa",
          "sostenibilidad empresarial", "responsabilidad social corporativa", "inversión sostenible",
          "Nachhaltigkeit Unternehmen", "Nachhaltigkeitsberichterstattung", "développement durable entreprise",
          "responsabilité sociale des entreprises", "keberlanjutan perusahaan", "pengungkapan ESG",
          "sürdürülebilirlik raporlaması", "kurumsal sosyal sorumluluk", "可持续发展 企业", "ESG投資", "sostenibilità impresa"]
# общий англоязычный блок ESG — добирает объём сверх узких направлений, глубже по страницам
GENERAL = ["ESG", "corporate sustainability performance", "corporate social responsibility financial performance",
           "sustainable finance", "green finance firms", "climate risk firms", "ESG disclosure", "sustainability reporting",
           "responsible investment", "carbon disclosure firm value"]
EXTRA = {  # дополнительные английские запросы к узким направлениям
    "02_XAI_ESG": ["explainable machine learning sustainability", "SHAP finance", "interpretable model green finance"],
    "08_Knowledge_graph_GNN": ["knowledge graph sustainability", "graph neural network ESG", "knowledge graph finance companies",
                               "supply chain network sustainability risk"],
    "03_Causal_ESG": ["causal machine learning finance", "instrumental variable CSR"],
    "07_Monitoring_remote_sensing_IoT": ["remote sensing corporate environmental", "satellite emissions facilities"],
}
WEIGHT = {"12_Non_English": 6, "00_ESG_general": 4}  # доля в очереди скачивания (у остальных — 2)
CACHE = Path(__file__).parent.parent / "data" / "fetch_more_candidates.json"


def api_json(url):
    # OpenAlex отвечает 429 при параллельных запросах — ждём дольше, чем get_json, и падаем, а не молча теряем выдачу
    for i in range(10):
        d = get_json(url, tries=1)
        if d is not None:
            return d
        time.sleep(5 * (i + 1))
    raise RuntimeError("OpenAlex не отвечает: " + url[:150])


def works(query, extra="", pages=MAX_PAGES):
    flt = f"title_and_abstract.search:{query},publication_year:>2017,is_oa:true,type:article|preprint|review{extra}"
    sel = "id,doi,title,publication_year,cited_by_count,language,best_oa_location,locations,authorships,abstract_inverted_index"
    cursor = "*"
    for _ in range(pages):
        d = api_json("https://api.openalex.org/works?" + urllib.parse.urlencode(
            {"filter": flt, "per_page": 200, "select": sel, "sort": "relevance_score:desc", "cursor": cursor}))
        if not d or not d.get("results"):
            return
        yield from d["results"]
        cursor = d["meta"].get("next_cursor")
        if not cursor:
            return


def to_cand(w):
    pdfs = []
    for loc in [w.get("best_oa_location")] + (w.get("locations") or []):
        u = (loc or {}).get("pdf_url")
        if u and u not in pdfs:
            pdfs.append(u)
    if not pdfs or not w.get("title"):
        return None
    text = (w["title"] + " " + " ".join((w.get("abstract_inverted_index") or {}).keys())).lower()
    if not DOMAIN.search(text):
        return None
    oid = w["id"].rsplit("/", 1)[-1]
    return {"id": oid, "doi": w.get("doi"), "title": w["title"], "year": w.get("publication_year"),
            "cited": w.get("cited_by_count", 0), "language": w.get("language") or "",
            "author": ((w.get("authorships") or [{}])[0].get("author") or {}).get("display_name", "") or "",
            "pdfs": pdfs}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    old = list(csv.DictReader(open(MANIFEST, encoding="utf-8-sig"))) if MANIFEST.exists() else []
    seen = {(r["doi"] or "").lower() for r in old if r["doi"]}
    have_files = {p.name for p in OUT.rglob("*.pdf")}
    need = TOTAL - len(have_files)
    print(f"уже есть {len(have_files)} PDF, докачиваем {need}", flush=True)

    jobs = [(t, q, ",language:en", MAX_PAGES) for t, qs in TOPICS.items() for q in qs + EXTRA.get(t, [])]
    jobs += [("00_ESG_general", q, ",language:en", 15) for q in GENERAL]
    jobs += [("12_Non_English", q, ",language:!en", MAX_PAGES) for q in NON_EN]
    if CACHE.exists():
        raw = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        with cf.ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda j: [c for c in map(to_cand, works(j[1], j[2], j[3])) if c], jobs))
        raw = [[j[0], cs] for j, cs in zip(jobs, res)]
        CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    pools = {}
    for t, cs in raw:                                    # порядок jobs: узкие направления раньше общего блока
        pool = pools.setdefault(t, [])
        for c in cs:
            key = (c["doi"] or c["id"]).lower()
            if key not in seen:
                seen.add(key)
                pool.append(c)
    for t, p in pools.items():
        p.sort(key=lambda c: -(c["cited"] or 0) / max(1, 2027 - (c["year"] or 2026)))
        print(f"{t}: {len(p)} новых кандидатов", flush=True)

    # единая очередь с чередованием направлений по весам
    order, qs = [], {t: list(p) for t, p in pools.items()}
    while any(qs.values()):
        for t, q in qs.items():
            for _ in range(WEIGHT.get(t, 2)):
                if q:
                    order.append((t, q.pop(0)))

    # манифест переписывается с колонкой language, старые строки сохраняются
    fh = open(MANIFEST, "w", newline="", encoding="utf-8-sig")
    wr = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
    wr.writeheader()
    wr.writerows({**r, "language": r.get("language") or "en"} for r in old)
    fh.flush()
    done, it = 0, iter(order)
    with cf.ThreadPoolExecutor(24) as ex:
        running = {}

        def submit():
            t, c = next(it)
            folder = OUT / t / (c["language"] or "xx") if t == "12_Non_English" else OUT / t
            folder.mkdir(parents=True, exist_ok=True)
            running[ex.submit(dl, c, folder)] = (t, c)
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
                if p and done < need:
                    done += 1
                    wr.writerow({"topic": t, "file": str(p.relative_to(OUT)), "title": c["title"], "year": c["year"],
                                 "language": c["language"], "doi": c["doi"], "cited_by": c["cited"]})
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
            p = f.result()                               # лишние сверх TOTAL — удалить, кроме старых файлов
            if p and p.name not in have_files:
                p.unlink()
    fh.close()
    print("ИТОГО новых", done, flush=True)


def dl(c, folder):
    # суффикс OpenAlex id исключает совпадение имён (в первом прогоне 3 файла перезаписали друг друга)
    c = dict(c, title=c["title"][:70] + "_" + c["id"])
    return download(c, folder)


if __name__ == "__main__":
    main()
