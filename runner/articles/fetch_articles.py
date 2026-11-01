"""Скачивает open-access PDF статей под задачи лаборатории (поиск через OpenAlex).

Направления = подпапки. Кандидаты набираются по нескольким запросам на направление, затем PDF качаются
по очереди (round-robin по направлениям), пока не наберётся TARGET успешно скачанных файлов.
"""
import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(sys.argv[1])
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 700
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

TOPICS = {
    "01_ESG_financial_performance_ML": [
        "ESG financial performance machine learning", "ESG neural network return on assets",
        "ESG scores predict firm profitability deep learning", "ESG corporate financial performance prediction",
        "sustainability performance firm value panel data", "ESG investment long-term financial performance"],
    "02_XAI_ESG": [
        "explainable artificial intelligence ESG", "SHAP ESG", "interpretable machine learning sustainability finance",
        "explainable AI credit risk ESG", "feature importance ESG rating machine learning"],
    "03_Causal_ESG": [
        "causal effect ESG firm performance", "double machine learning ESG", "causal inference corporate sustainability",
        "Bayesian network ESG", "fuzzy cognitive map sustainability", "difference-in-differences ESG disclosure"],
    "04_Decision_support_ESG_investment": [
        "ESG portfolio optimization", "multi-criteria decision making ESG", "fuzzy TOPSIS sustainability investment",
        "decision support system sustainable investment", "green investment project selection", "ESG investment allocation"],
    "05_ESG_ratings_divergence_criteria": [
        "ESG rating divergence", "ESG ratings disagreement", "ESG rating methodology critique",
        "ESG scores measurement validity", "sustainability rating agencies"],
    "06_NLP_LLM_reports_greenwashing": [
        "ESG report natural language processing", "large language model ESG disclosure", "greenwashing detection",
        "sustainability report text analysis", "climate disclosure NLP", "ESG news sentiment"],
    "07_Monitoring_remote_sensing_IoT": [
        "satellite remote sensing ESG", "emissions monitoring deep learning satellite", "IoT environmental monitoring corporate",
        "digital twin sustainability industry", "carbon emissions estimation machine learning companies"],
    "08_Knowledge_graph_GNN": [
        "knowledge graph ESG", "graph neural network supply chain risk", "ESG ontology",
        "graph neural network financial risk companies"],
    "09_Project_valuation_NPV_behavioral": [
        "net present value sustainability project", "real options green investment", "valuation of ESG investments",
        "neural network cash flow forecasting", "behavioral economics sustainability investment",
        "non-financial factors investment decision"],
    "10_ESG_social_impact_SDG": [
        "ESG investment sustainable development goals impact", "impact investing outcomes", "corporate social responsibility social impact measurement",
        "ESG regional development"],
    "11_Russia_emerging_markets": [
        "ESG Russia", "ESG emerging markets", "устойчивое развитие ESG компании", "ESG-рейтинг", "ESG Russian companies"],
}


def get_json(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 + 3 * i)
    return None


def candidates(query, n=200):
    flt = f"title_and_abstract.search:{query},publication_year:>2017,is_oa:true,type:article|preprint|review"
    sel = "id,doi,title,publication_year,cited_by_count,best_oa_location,locations,authorships"
    url = ("https://api.openalex.org/works?" + urllib.parse.urlencode(
        {"filter": flt, "per_page": n, "select": sel, "sort": "relevance_score:desc"}))
    d = get_json(url)
    out = []
    for w in (d or {}).get("results", []):
        pdfs = []
        for loc in [w.get("best_oa_location")] + (w.get("locations") or []):
            u = (loc or {}).get("pdf_url")
            if u and u not in pdfs:
                pdfs.append(u)
        if pdfs and w.get("title"):
            out.append({"id": w["id"].rsplit("/", 1)[-1], "doi": w.get("doi"), "title": w["title"],
                        "year": w.get("publication_year"), "cited": w.get("cited_by_count", 0),
                        "author": ((w.get("authorships") or [{}])[0].get("author") or {}).get("display_name", "") or "",
                        "pdfs": pdfs})
    return out


def safe_name(c):
    a = re.sub(r"[^\w]+", "", (c["author"].split() or ["NA"])[-1])[:20] or "NA"
    t = re.sub(r"[^\w\s-]", "", c["title"])
    t = re.sub(r"\s+", "_", t.strip())[:80]
    return f"{c['year']}_{a}_{t}.pdf"


def download(c, folder):
    dst = folder / safe_name(c)
    if dst.exists() and dst.stat().st_size > 10000:
        return dst
    for u in c["pdfs"]:
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
                data = r.read(60_000_000)
            if data[:5] == b"%PDF-" and len(data) > 20000:
                dst.write_bytes(data)
                return dst
        except Exception:
            continue
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seen, pools = set(), {}
    for topic, qs in TOPICS.items():
        pool = []
        for q in qs:
            for c in candidates(q):
                key = (c["doi"] or c["id"]).lower()
                if key not in seen:
                    seen.add(key)
                    pool.append(c)
        # приоритет — цитируемость в год: отсекает малозаметные публикации, не наказывая свежие
        pool.sort(key=lambda c: -(c["cited"] or 0) / max(1, 2027 - (c["year"] or 2026)))
        pools[topic] = pool
        (OUT / topic).mkdir(exist_ok=True)
        print(f"{topic}: {len(pool)} кандидатов", flush=True)

    manifest, done = [], 0
    queues = {t: list(p) for t, p in pools.items()}
    with cf.ThreadPoolExecutor(12) as ex:
        while done < TARGET and any(queues.values()):
            batch = []
            for t, q in queues.items():           # round-robin, по 2 кандидата с направления за круг
                for _ in range(2):
                    if q:
                        batch.append((t, q.pop(0)))
            futs = {ex.submit(download, c, OUT / t): (t, c) for t, c in batch}
            for f in cf.as_completed(futs):
                t, c = futs[f]
                (OUT / t).mkdir(exist_ok=True)
                p = f.result()
                if p and done < TARGET:
                    done += 1
                    manifest.append({"topic": t, "file": p.name, "title": c["title"], "year": c["year"], "doi": c["doi"],
                                     "cited_by": c["cited"]})
                elif p:
                    p.unlink()
            print(f"скачано {done}", flush=True)
    import csv
    with open(OUT / "_список_статей.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["topic", "file", "title", "year", "doi", "cited_by"])
        w.writeheader(); w.writerows(manifest)
    print("ИТОГО", done)


if __name__ == "__main__":
    main()
