"""Нагрузочная проверка: N одновременных пользователей ходят по типичным страницам.

    python deploy/loadtest.py site --users 20 --minutes 2          через сайт (nginx → backend → KBRAG)
    python deploy/loadtest.py kbrag --users 20 --minutes 2         только KBRAG: поиск и граф

site: вход логином и паролем из LOADTEST_LOGIN / LOADTEST_PASSWORD (лучше отдельная учётная
запись с ролью reader), адрес — https://127.0.0.1:<HTTP_PORT из deploy/.env>, корневой
сертификат — deploy/certs/lab-root-ca.crt. Каждый «пользователь» по кругу открывает обзор,
реестр экспериментов, карточку эксперимента, поиск в базе знаний и граф.
kbrag: то же для поиска и графа напрямую в KBRAG (KBRAG_URL, токен KBRAG_TOKEN из deploy/.env).

Запуски в нагрузку не входят: их предел — очередь исполнителя, а не число зрителей. Итог — задержки p50/p95/max и ошибки по каждому адресу.
Только стандартная библиотека.
"""

import argparse
import json
import os
import ssl
import statistics
import threading
import time
from collections import defaultdict
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

DEPLOY = Path(__file__).resolve().parent
QUERIES = ["ESG и стоимость капитала", "ESG rating divergence", "раскрытие нефинансовой информации",
           "SHAP explainability ESG", "greenwashing", "ROA ESG score panel regression",
           "ESG-рейтинг RAEX", "carbon emissions firm value"]
BRANCHES = ["esg", "esg.finance", "esg.ratings", "esg.xai"]


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = DEPLOY / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.times: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, list[str]] = defaultdict(list)

    def add(self, name: str, seconds: float, error: str = "") -> None:
        with self.lock:
            if error:
                self.errors[name].append(error)
            else:
                self.times[name].append(seconds)

    def report(self, wall: float) -> None:
        total = sum(len(v) for v in self.times.values())
        fails = sum(len(v) for v in self.errors.values())
        print(f"\n{'адрес':<34}{'запросов':>9}{'p50, с':>9}{'p95, с':>9}{'max, с':>9}{'ошибок':>8}")
        for name in sorted(set(self.times) | set(self.errors)):
            t = sorted(self.times.get(name, []))
            p = (lambda q: t[min(len(t) - 1, int(q * len(t)))] if t else float("nan"))
            print(f"{name:<34}{len(t):>9}{statistics.median(t) if t else float('nan'):>9.2f}"
                  f"{p(0.95):>9.2f}{(t[-1] if t else float('nan')):>9.2f}{len(self.errors.get(name, [])):>8}")
        print(f"\nвсего {total} запросов за {wall:.0f} с ({total / wall:.1f} в секунду), ошибок {fails}")
        for name, errs in self.errors.items():
            print(f"  {name}: {errs[0]}" + (f" (и ещё {len(errs) - 1})" if len(errs) > 1 else ""))


def site_user(base: str, ctx: ssl.SSLContext, login: str, password: str, stats: Stats,
              stop: float, n: int) -> None:
    opener = build_opener(HTTPCookieProcessor(CookieJar()), HTTPSHandler(context=ctx))

    def get(name: str, path: str, data: dict | None = None) -> object:  # type: ignore[type-arg]
        t0 = time.perf_counter()
        body = json.dumps(data).encode() if data is not None else None
        req = Request(base + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=60) as r:
                out = json.loads(r.read() or b"null")
            stats.add(name, time.perf_counter() - t0)
            return out
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            stats.add(name, time.perf_counter() - t0, f"{type(exc).__name__}: {exc}"[:200])
            return None

    if get("POST /api/auth/login", "/api/auth/login", {"login": login, "password": password}) is None:
        return
    i = n
    while time.time() < stop:
        q, kb = QUERIES[i % len(QUERIES)], BRANCHES[i % len(BRANCHES)]
        get("GET /api/experiments", "/api/experiments")
        get("GET /api/experiments/EXP-007", "/api/experiments/EXP-007")
        get("GET /api/hypotheses", "/api/hypotheses")
        get("GET /api/kb/stats", "/api/kb/stats?" + urlencode({"kb": "esg"}))
        get("GET /api/kb/search", "/api/kb/search?" + urlencode({"q": q, "kb": kb, "limit": 12}))
        get("GET /api/kb/network", "/api/kb/network?" + urlencode({"kb": kb}))
        get("GET /api/runs", "/api/runs")
        i += 1


def kbrag_user(base: str, token: str, stats: Stats, stop: float, n: int) -> None:
    opener = build_opener()
    i = n
    while time.time() < stop:
        q, kb = QUERIES[i % len(QUERIES)], BRANCHES[i % len(BRANCHES)]
        for name, path in (("search", "/api/search?" + urlencode({"q": q, "kb": kb, "limit": 12})),
                           ("network", "/api/network?" + urlencode({"kb": kb})),
                           ("stats", "/api/stats?" + urlencode({"kb": "esg"}))):
            t0 = time.perf_counter()
            try:
                with opener.open(Request(base + path, headers={"X-KBRAG-Token": token}), timeout=60) as r:
                    r.read()
                stats.add(name, time.perf_counter() - t0)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                stats.add(name, time.perf_counter() - t0, f"{type(exc).__name__}: {exc}"[:200])
        i += 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["site", "kbrag"])
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--minutes", type=float, default=2)
    ap.add_argument("--url", help="адрес сайта или KBRAG вместо адреса по умолчанию")
    args = ap.parse_args()
    env = read_env()
    stats = Stats()
    stop = time.time() + args.minutes * 60
    if args.mode == "site":
        login, password = os.environ.get("LOADTEST_LOGIN", ""), os.environ.get("LOADTEST_PASSWORD", "")
        if not (login and password):
            print("Задайте LOADTEST_LOGIN и LOADTEST_PASSWORD (учётная запись для проверки)")
            return 1
        base = (args.url or f"https://127.0.0.1:{env.get('HTTP_PORT', '8080')}").rstrip("/")
        ctx = ssl.create_default_context(cafile=str(DEPLOY / "certs" / "lab-root-ca.crt"))
        target = lambda n: site_user(base, ctx, login, password, stats, stop, n)  # noqa: E731
    else:
        base = (args.url or "http://127.0.0.1:8000").rstrip("/")
        target = lambda n: kbrag_user(base, env.get("KBRAG_TOKEN", ""), stats, stop, n)  # noqa: E731
    print(f"{args.mode}: {args.users} пользователей, {args.minutes} мин → {base}")
    t0 = time.time()
    threads = [threading.Thread(target=target, args=(n,), daemon=True) for n in range(args.users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stats.report(time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
