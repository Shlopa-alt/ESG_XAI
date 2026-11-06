"""Обработчик очереди задач Qwen: модель на видеокарте — только пока есть работа.

    py -3.12 runner/qwen/worker.py              работать постоянно (так его запускает start_all.ps1)
    py -3.12 runner/qwen/worker.py --once       разобрать очередь и выйти
    ... --idle-min 10                           сколько минут простоя до выключения модели

Цикл: раз в 15 с — есть ли задачи в очереди платформы (/api/qwen/worker/peek). Есть — поднять
vLLM (`docker compose --profile llm up -d llm` в KBRAG) и дождаться готовности, затем брать
задачи по одной и выполнять. Очередь пуста дольше --idle-min — остановить модель, если её
поднимал этот обработчик (модель, запущенную вручную, он не трогает). Раз в 30 с — отметка
платформе: состояние модели и память видеокарты (её видно на странице «Задачи Qwen»).

Задачи (kind):
  ping       — проверка: модель отвечает
  graph      — достроить граф фактов KBRAG по новым фрагментам (`kbrag.py graph --kb <ветка>`)
  hypotheses — по каждому заданию методики: фрагменты статей и факты графа из KBRAG + датасеты и
               методы платформы → Qwen предлагает проверяемые гипотезы со ссылками на фрагменты;
               платформа проверяет опоры и ставит гипотезы на рецензию
  experiment — по принятой гипотезе: метод из библиотеки, срез, параметры (столбцы), протокол и что
               подтвердит или опровергнет гипотезу; платформа проверяет и показывает человеку
  report     — текст отчёта по завершённому эксперименту: резюме, вердикт по гипотезе, интерпретация,
               что это значит для задания методики, ограничения, что дальше; цифры и графики — из
               run.json, числа текста платформа сверяет с расчётом

Только стандартная библиотека. Настройки — deploy/.env (QWEN_TOKEN, HTTP_PORT, KBRAG_TOKEN),
KBRAG_HOME, KBRAG_DSN, KBRAG_WEB (веб-сервер KBRAG, по умолчанию http://127.0.0.1:8000).
"""

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"
DOCKER = os.environ.get("DOCKER", r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
LLM_URL = os.environ.get("KBRAG_LLM", "http://127.0.0.1:8100").rstrip("/")
LLM_CONTAINER = "kbrag-llm"
KBRAG_WEB = os.environ.get("KBRAG_WEB", "http://127.0.0.1:8000").rstrip("/")
POLL_S = 15
BEAT_S = 30


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


class Platform:
    def __init__(self, url: str, token: str, ca: Path) -> None:
        self.url = url.rstrip("/")
        self.token = token
        # Системные корневые сертификаты (Let's Encrypt на сервере) + корневой лаборатории, если есть
        self.ctx = ssl.create_default_context()
        if ca.is_file():
            self.ctx.load_verify_locations(cafile=str(ca))

    def post(self, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        req = Request(f"{self.url}/api/qwen/worker/{path}", data=json.dumps(body or {}).encode(),
                      headers={"X-Qwen-Token": self.token, "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=60, context=self.ctx) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except HTTPError as exc:
            raise RuntimeError(f"платформа ответила {exc.code}: {exc.read()[:300]!r}") from exc


class Model:
    """vLLM в контейнере KBRAG: поднять, дождаться, остановить; состояние для отметки."""

    def __init__(self, kbrag: Path, flag: Path) -> None:
        self.kbrag = kbrag
        self.flag = flag  # «модель поднимал обработчик» — переживает перезапуск обработчика
        self.state = "on" if self.up() else "off"
        self.detail = ""

    @property
    def started_by_me(self) -> bool:
        return self.flag.exists()

    @started_by_me.setter
    def started_by_me(self, value: bool) -> None:
        if value:
            self.flag.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        else:
            self.flag.unlink(missing_ok=True)

    @staticmethod
    def up() -> bool:
        try:
            with urlopen(f"{LLM_URL}/v1/models", timeout=3) as r:
                return r.status == 200
        except (URLError, TimeoutError, OSError):
            return False

    def start(self, wait_s: int = 900) -> bool:
        if self.up():
            self.state = "on"
            return True
        self.state, self.detail = "starting", "поднимаю модель"
        log("поднимаю vLLM")
        r = subprocess.run([DOCKER, "compose", "--profile", "llm", "up", "-d", "llm"], cwd=self.kbrag,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            self.state, self.detail = "off", f"не поднялась: {r.stderr.strip()[-300:]}"
            log(self.detail)
            return False
        self.started_by_me = True
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if self.up():
                self.state, self.detail = "on", ""
                log(f"модель готова за {time.time() - t0:.0f} с")
                return True
            time.sleep(5)
        self.state, self.detail = "off", f"не ответила за {wait_s // 60} мин — журнал: docker logs {LLM_CONTAINER}"
        log(self.detail)
        return False

    def stop(self) -> None:
        if not self.started_by_me:
            return
        self.state = "stopping"
        log("очередь пуста — останавливаю модель, видеокарта свободна")
        subprocess.run([DOCKER, "stop", LLM_CONTAINER], capture_output=True)
        self.state, self.started_by_me = "off", False


def gpu() -> tuple[int | None, int | None]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        used, total = (int(x) for x in out.split(","))
        return used, total
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None


def chat(prompt: str, max_tokens: int = 200, system: str = "", schema: dict[str, Any] | None = None,
         temperature: float = 0.3) -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt + " /no_think"}]
    body: dict[str, Any] = {"model": "qwen3-14b", "max_tokens": max_tokens, "temperature": temperature,
                            "messages": messages}
    if schema is not None:
        # vLLM выводит ровно по схеме: с «просто JSON» модель иногда отвечала пустым {}
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
    req = Request(f"{LLM_URL}/v1/chat/completions", data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=300) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def ask_json(prompt: str, max_tokens: int, system: str, schema: dict[str, Any],
             temperature: float = 0.3) -> dict[str, Any]:
    """Ответ модели по JSON-схеме; не разобрался или без обязательных полей — ещё одна попытка."""
    required = schema.get("required", [])
    for _ in range(2):
        try:
            data = json.loads(chat(prompt, max_tokens, system, schema, temperature))
        except ValueError:
            continue
        if isinstance(data, dict) and all(k in data for k in required):
            return data
    raise ValueError("модель не дала ответ по схеме")


_S, _I = {"type": "string"}, {"type": "integer"}
PLAN_SCHEMA = {"type": "object", "required": ["queries", "entities"], "properties": {
    "queries": {"type": "array", "items": _S, "maxItems": 3}, "entities": {"type": "array", "items": _S, "maxItems": 5}}}
HYP_SCHEMA = {"type": "object", "required": ["hypotheses"], "properties": {"hypotheses": {
    "type": "array", "maxItems": 3, "items": {"type": "object", "required": [
        "title", "statement", "rationale", "fragments", "dataset", "method", "data_needed"], "properties": {
        "title": _S, "statement": _S, "rationale": _S, "fragments": {"type": "array", "items": _I},
        "dataset": _S, "method": _S, "data_needed": _S}}}}}
LEVELS = ["компания", "бюджет региона", "федеральный бюджет", "регион (не бюджет)", "ESG-рейтинг", "другое"]
DIRECTIONS = ["рост", "снижение", "связь без знака", "не сказано"]
INVESTMENT = "объём ESG-инвестиций или затрат"
FACTORS = [INVESTMENT, "ESG-рейтинг или балл", "раскрытие ESG-информации", "ESG-практики или политика", "другое"]
# чем заменён объём инвестиций — для пометки в названии: «… (по ESG-рейтингу)»
PROXY_SHORT = {"ESG-рейтинг или балл": "ESG-рейтингу", "раскрытие ESG-информации": "раскрытию ESG",
               "ESG-практики или политика": "ESG-практикам"}
PROXY_SAID = re.compile(r"замен|вместо|прокси|приближ", re.IGNORECASE)
SCOPES = ["Россия", "другие страны или мир", "Россия и другие страны", "не сказано"]
ABROAD = "другие страны или мир"
RUSSIA = re.compile(r"росси|\bрф\b|отечествен", re.IGNORECASE)
ABROAD_SAID = re.compile(r"зарубеж|междунар|иностран|других стран|по аналогии", re.IGNORECASE)
# порядок полей — порядок вывода: сначала разбор и цитаты, решения принимает код (_verify)
CHECK_SCHEMA = {"type": "object", "required": [
    "task_level", "factor", "factor_kind", "outcome", "level", "refs_level", "refs_factor_kind", "direction",
    "link_quote", "link_scope", "refs_direction", "direction_quote", "comment"], "properties": {
    "task_level": {"type": "string", "enum": LEVELS}, "factor": _S,
    "factor_kind": {"type": "string", "enum": FACTORS}, "outcome": _S,
    "level": {"type": "string", "enum": LEVELS}, "refs_level": {"type": "string", "enum": LEVELS},
    "refs_factor_kind": {"type": "string", "enum": FACTORS},
    "direction": {"type": "string", "enum": DIRECTIONS}, "link_quote": _S,
    "link_scope": {"type": "string", "enum": SCOPES},
    "refs_direction": {"type": "string", "enum": DIRECTIONS}, "direction_quote": _S, "comment": _S}}


# --- задачи ---


def job_ping(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    answer = chat("Ответь одним словом по-русски: готова ли ты к работе?", 20)
    return {"answer": answer, "seconds": round(time.time() - t0, 1)}


def job_graph(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Граф фактов по новым фрагментам ветки: готовое не пересчитывается."""
    kb = str(job["payload"].get("kb") or "esg")
    if not re.fullmatch(r"esg(\.[a-z0-9_]+)*", kb):
        raise ValueError(f"ветка не из дерева esg: {kb}")
    kbrag: Path = ctx["kbrag"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.setdefault("KBRAG_DSN", "postgresql://kbrag:kbrag@127.0.0.1:5434/kbrag")
    log_path = ctx["logs"] / f"qwen-graph-{job['id']}.log"
    with log_path.open("w", encoding="utf-8") as out:
        code = subprocess.run([str(kbrag / ".venv" / "Scripts" / "python.exe"), "kbrag.py", "graph", "--kb", kb],
                              cwd=kbrag, env=env, stdout=out, stderr=subprocess.STDOUT).returncode
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result: dict[str, Any] = {"kb": kb, "log": str(log_path)}
    m = re.search(r"Пройдено фрагментов: (\d+) из (\d+)", text)
    if m:
        result["fragments"] = int(m.group(1))
    m = re.search(r"Фактов принято: (\d+); отброшено проверкой: (\d+)", text)
    if m:
        result["facts_accepted"], result["facts_rejected"] = int(m.group(1)), int(m.group(2))
    if code != 0:
        raise RuntimeError(f"kbrag.py graph завершился с кодом {code}; журнал: {log_path}")
    if "fragments" not in result and re.search(r"нов\w* фрагмент\w* нет|нечего", text, re.I):
        result["fragments"] = 0
    return result


def kbrag_get(path: str, params: dict[str, Any], token: str, timeout_s: float = 20) -> Any:
    req = Request(f"{KBRAG_WEB}/api/{path}?{urlencode(params)}", headers={"X-KBRAG-Token": token})
    with urlopen(req, timeout=timeout_s) as r:
        return json.loads(r.read())


def query_text(text: str, limit: int = 300) -> str:
    """Запрос к поиску — по границе слова: обрезок слова («функционал» из «функциональной»)
    вешает поиск KBRAG больше чем на минуту."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]


HYP_SYSTEM = """Ты — исследователь НИЦ ИИ (Университет «Дубна») и Лаборатории технологий ИНС для управления бизнесом в формате ESG. Ты предлагаешь гипотезы для задания
методики лаборатории. Гипотеза — проверяемое утверждение о связи (что влияет на что, в какую сторону, на
каком горизонте, на каких данных), которое можно подтвердить или опровергнуть расчётом.

Правила:
1. Опирайся ТОЛЬКО на пронумерованные опоры ниже (фрагменты статей и факты графа). Каждая гипотеза ссылается на
   номера опор, из которых она следует (поле "fragments"). Без опоры гипотезу не предлагай.
2. Гипотеза должна служить заданию: те же входы и выходы, что в задании и его разделах.
3. Не повторяй гипотезы, которые уже есть.
4. "dataset" — код датасета из списка, только если в его описании есть нужные показатели; иначе "" и в
   "data_needed" — какие данные нужны и где их взять. Датасет и "data_needed" вместе не бывают.
5. "method" — ключ метода из списка, только если этот метод считается на выбранном датасете и действительно
   проверяет утверждение. Метод «Повтор …» пересчитывает опубликованную работу как есть: бери его, только
   если гипотеза о воспроизведении именно этой работы; иначе
   коротко словами: каким методом проверять.
6. Пиши по-русски; названия показателей и терминов из статей можно оставить как в статье.
7. Горизонт — ровно тот, что в задании: в задании 3 года — пиши 3 года, не «3–5 лет».
8. Опоры о зарубежных данных, а задание о России — так и пиши: «по зарубежным данным …; для России
   проверить». Числа из зарубежных опор — ориентир для сравнения, не ожидаемое значение для России.
   Названий агентств, компаний и регионов, которых нет в опорах и задании, не добавляй.
9. Если опоры говорят не о том показателе, что в задании (ESG-рейтинг или раскрытие вместо объёма
   ESG-инвестиций, прибыль компаний вместо налогов в бюджет), скажи это в утверждении прямо: «ESG-рейтинг как
   замена объёма ESG-инвестиций». Не выдавай одно за другое.
10. Знак связи («повышает», «улучшает», «положительно») пиши, только если опора его называет. Опоры говорят
   только, что связь есть, или знак у них разный (в краткосроке хуже, в долгосроке лучше) — пиши «связан с»:
   знак покажет расчёт.
11. Лучше 1 хорошо обоснованная гипотеза, чем 3 слабых. Нечего предложить — верни пустой список.

Ответ — только JSON: {"hypotheses": [{"title": "коротко, до 120 знаков", "statement": "проверяемое
утверждение", "rationale": "почему так думаем, со ссылками [n] на фрагменты", "fragments": [1, 3],
"dataset": "код из списка или пусто", "method": "ключ из списка или словами", "data_needed": "пусто, если датасет выбран"}]}"""

DOI = re.compile(r"10\.\d{4,9}/\S+")


PLAN_SYSTEM = """Ты помогаешь искать в базе научных статей об ESG (статьи в основном на английском).
По заданию методики составь: "queries" — 3 коротких поисковых запроса (до 12 слов каждый, минимум два
на английском, как пишут в статьях), "entities" — до 5 ключевых показателей и понятий задания
по-английски, как их называют в статьях (например: "ESG investments", "ROA", "tax revenue").
Ответ — только JSON: {"queries": ["…"], "entities": ["…"]}"""


def _plan(target: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Короткие запросы и сущности по заданию — от Qwen; длинный текст задания поиск не любит."""
    text = f"Задание: {target['title']}\n{target['content'][:1500]}"
    try:
        data = ask_json(text, 300, PLAN_SYSTEM, PLAN_SCHEMA)
    except (ValueError, TimeoutError, URLError, OSError):
        data = {}
    queries = [query_text(str(q), 120) for q in data.get("queries") or [] if str(q).strip()][:3]
    entities = [str(e).strip()[:80] for e in data.get("entities") or [] if str(e).strip()][:5]
    return queries or [target["title"]], entities


FRAGMENTS, PER_QUERY, FACTS, FACTS_PER_ENTITY = 8, 4, 6, 2
CELL = re.compile(r"\S\s=\s\S")  # «ROA, 1 = 0.011», «Improvement (%) = +20%» — ячейки таблицы из PDF
TABLE_HEAD = re.compile(r"\s*(table|таблица|panel|рис|fig)", re.IGNORECASE)


def _is_prose(text: str) -> bool:
    """Связный текст, а не таблица, формула или подпись: из таблиц модель вычитывала «коэффициент при ROA»."""
    t = text[:800]
    if not t:
        return False
    letters = sum(ch.isalpha() for ch in t) / len(t)
    digits = sum(ch.isdigit() for ch in t) / len(t)
    markup = sum(t.count(ch) for ch in "=|$\\")
    return (letters > 0.6 and digits < 0.12 and markup < 6 and len(CELL.findall(t)) < 3
            and not TABLE_HEAD.match(t))


def _own_reports(token: str) -> set[str]:
    """Отчёты лаборатории в базе знаний: их текст писала сама Qwen, поэтому опорой он быть не может —
    иначе гипотеза опиралась бы на собственный пересказ."""
    try:
        docs = kbrag_get("documents", {"kb": "esg.experiments"}, token, timeout_s=30).get("documents") or []
    except (TimeoutError, URLError, OSError, ValueError) as exc:
        log(f"  список отчётов лаборатории не получен ({exc}) — опоры без этого фильтра")
        return set()
    return {str(d.get("doc_id")) for d in docs if d.get("doc_id")}


def _evidence(target: dict[str, Any], token: str, exclude: frozenset[str] | set[str] = frozenset()) -> list[dict[str, Any]]:
    """Опоры по заданию: фрагменты статей по коротким запросам и факты графа о ключевых сущностях
    (у каждого факта — дословная цитата из статьи). Материалы лаборатории (lab_*) — сама
    постановка, не опора.

    Фрагменты берутся по кругу — лучший с каждого запроса, затем второй… — чтобы каждый запрос дошёл
    до модели; длинное русское название задания — последним (раньше оно занимало 5 мест из 8)."""
    queries, entities = _plan(target)
    ranked: list[list[dict[str, Any]]] = []
    for q in [*queries, target["title"]]:
        try:
            found = kbrag_get("search", {"q": query_text(q, 120), "kb": "esg", "limit": PER_QUERY + 4},
                              token).get("hits", [])
        except (TimeoutError, URLError, OSError) as exc:
            log(f"  поиск «{q[:60]}» не ответил ({exc}) — пропускаю запрос")
            continue
        ranked.append([h for h in found if not h["doc_id"].startswith("lab_") and h["doc_id"] not in exclude
                       and _is_prose(h["text"])][:PER_QUERY])
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for rank in range(PER_QUERY):
        for hits in ranked:
            if rank >= len(hits) or hits[rank]["chunk_id"] in seen or len(items) >= FRAGMENTS:
                continue
            h = hits[rank]
            seen.add(h["chunk_id"])
            items.append({"kind": "fragment", "doc_id": h["doc_id"], "title": h["title"], "year": h.get("year"),
                          "url": h.get("url"), "pages": h.get("pages") or [], "text": " ".join(h["text"].split())})
    known: set[str] = set()
    for name in entities:
        try:
            ds = kbrag_get("dataset", {"name": name, "kb": "esg"}, token)
        except (TimeoutError, URLError, OSError, HTTPError):
            continue
        # сначала связи с направлением: «повышает», «снижает», «не влияет на»
        facts = sorted(ds.get("facts") or [], key=lambda f: (not re.search(r"повыша|снижа|не влияет", f["relation"]),
                                                              -f.get("documents", 0)))
        taken = 0
        for f in facts:
            if taken >= FACTS_PER_ENTITY or sum(it["kind"] == "fact" for it in items) >= FACTS:
                break
            q = (f.get("quotes") or [{}])[0]
            a, b = (f["other"], f["about"]) if f.get("direction") == "←" else (f["about"], f["other"])
            key = f"{a}|{f['relation']}|{b}".lower()  # один и тот же факт приходит от разных сущностей
            if not q.get("doc_id") or q["doc_id"].startswith("lab_") or q["doc_id"] in exclude or key in known:
                continue
            known.add(key)
            taken += 1
            items.append({"kind": "fact", "doc_id": q["doc_id"], "title": q.get("title") or "", "year": q.get("year"),
                          "url": q.get("url"), "pages": [], "fact": f"{a} — {f['relation']} — {b}",
                          "text": " ".join((q.get("quote") or "").split())})
    log(f"  {target['number']}: запросы {queries}, сущности {entities}")
    return items


def _prompt(target: dict[str, Any], ctx: dict[str, Any], items: list[dict[str, Any]]) -> str:
    path = " → ".join(p["title"] for p in target["path"])
    sections = "\n".join(f"- {s['number']} {s['title']}: {s['content'][:500]}" for s in target["sections"])
    datasets = "\n".join(f"- {d['code']} «{d['title']}» (срезов: {d['snapshots']}): {d['description'][:300]}"
                         for d in ctx["datasets"])
    methods = "\n".join(f"- {m['key']}: {m['title']}. {m['description']} (датасет {m['dataset']})"
                        for m in ctx["methods"])
    existing = "\n".join(f"- {h['code']}: {h['title']} ({h['status']})" for h in target["existing"]) or "- нет"
    lines = []
    for i, it in enumerate(items, start=1):
        src = f"«{it['title']}» ({it.get('year') or 'год ?'})"
        if it["kind"] == "fact":
            lines.append(f"[{i}] ФАКТ ГРАФА: {it['fact']}. Цитата: «{it['text'][:400]}» — {src}")
        else:
            lines.append(f"[{i}] ФРАГМЕНТ {src}, с. {', '.join(map(str, it['pages'])) or '?'}:\n{it['text'][:650]}")
    return (f"ЗАДАНИЕ {target['number']} ({path}): {target['title']}\n{target['content']}\n\n"
            f"РАЗДЕЛЫ МЕТОДИКИ, КОТОРЫЕ ДЕЙСТВУЮТ НА ЗАДАНИЕ:\n{sections or '- нет'}\n\n"
            f"ДАТАСЕТЫ ПЛАТФОРМЫ:\n{datasets or '- нет'}\n\nМЕТОДЫ (готовые расчёты):\n{methods or '- нет'}\n\n"
            f"УЖЕ ЕСТЬ ГИПОТЕЗЫ ПО ЗАДАНИЮ:\n{existing}\n\n"
            "ОПОРЫ ИЗ БАЗЫ ЗНАНИЙ (фрагменты статей и факты графа с цитатами):\n" + "\n\n".join(lines) +
            f"\n\nПредложи до {ctx['limits']['per_run']} гипотез по правилам; в \"fragments\" — номера опор.")


def _parse(text: str) -> list[dict[str, Any]]:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0) if m else text)
    except ValueError:
        return []
    items = data.get("hypotheses") if isinstance(data, dict) else None
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def _ref(it: dict[str, Any]) -> dict[str, Any]:
    doi = DOI.search(it.get("url") or "")
    quote = it["text"][:500] if it["kind"] == "fragment" else f"{it['fact']}: «{it['text'][:450]}»"
    return {"doc_id": it["doc_id"], "title": it["title"], "kb_path": "esg", "doi": doi.group(0) if doi else "",
            "quote": quote, "page": (it.get("pages") or [None])[0]}


CHECK_SYSTEM = """Ты — строгий рецензент лаборатории. Тебе дают задание методики, утверждение гипотезы и
пронумерованные опоры (цитаты из статей). Разбери, не оценивая заранее:
- "task_level": о чьём результате задание (компания, бюджет региона, федеральный бюджет, регион (не бюджет),
  ESG-рейтинг, другое);
- "factor": что в утверждении влияет; "factor_kind": чем этот фактор выражен в утверждении (объём
  ESG-инвестиций или затрат, ESG-рейтинг или балл, раскрытие ESG-информации, ESG-практики или политика,
  другое); "outcome": на какой показатель; "level": чей это показатель (из списка уровней);
- "refs_level": о чьих показателях говорят САМИ ОПОРЫ; "refs_factor_kind": чем фактор выражен В ОПОРАХ
  (тот же список): статья про ESG-балл компаний — это «ESG-рейтинг или балл», даже если в ней есть слово
  «инвестиции»;
- "direction": какую связь утверждает гипотеза;
- "link_quote": ДОСЛОВНО скопируй из опор (на языке опоры, без перевода, 5–30 слов) место, где сказано, что
  ИМЕННО этот фактор связан ИМЕННО с этим показателем. Нет такого места — пустая строка "";
- "link_scope": на чьих данных получена связь из "link_quote" — Россия, другие страны или мир (MSCI,
  Sustainalytics, компании США, Европы, Китая), Россия и другие страны вместе, не сказано;
- "refs_direction": какую связь фактора с показателем называют сами опоры;
- "direction_quote": ДОСЛОВНО место из опор о направлении связи; нет — "";
- "comment": одной фразой по-русски, чего не хватает.
Перефразировать цитаты нельзя. Похожие слова — не то же самое: «ESG-рейтинг» ≠ «ESG-инвестиции»,
«раскрытие ESG» ≠ «ESG-инвестиции», прибыль компании ≠ налоги в бюджет.
Ответ — только JSON по схеме."""

# с начала слова: «снижение выбросов» в названии фактора — не знак связи («ниже» внутри «снижение»)
SIGNED = re.compile(r"\b(?:положительн|отрицательн|повыша|понижа|снижа|увелич|уменьш|рост|выше|ниже|лучше|хуже|улучш|ухудш|"
                    r"сильнее|слабее|больше|меньше)", re.IGNORECASE)
# Qwen иногда вставляет китайские (реже японские, корейские) слова: «финансовую绩效 компании»
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")
YEARS = re.compile(r"(\d+)\s*(?:[-–—]\s*(\d+)\s*)?(?:-?\s*летн|год|года|лет|year|yr)", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def _quoted(quote: str, sources: list[str]) -> bool:
    """Цитата есть в одной из опор: дословно с точностью до пробелов и знаков или почти — 85 % слов
    и хотя бы четыре слова подряд (модель иногда пропускает слово или ставит другое окончание)."""
    words = _norm(quote).split()
    if len(words) < 4:
        return False
    q = " ".join(words)
    for src in map(_norm, sources):
        if q in src:
            return True
        padded = f" {src} "
        if (sum(f" {w} " in padded for w in words) / len(words) >= 0.85
                and any(" ".join(words[i:i + 4]) in src for i in range(len(words) - 3))):
            return True
    return False


def _years(text: str) -> set[str]:
    return {n for m in YEARS.finditer(text) for n in m.groups() if n}


def _verify(h: dict[str, Any], cited: list[dict[str, Any]],
            target: dict[str, Any]) -> tuple[bool, str, dict[str, Any], bool]:
    """Вторая пара глаз: гипотеза отвечает заданию и следует из процитированных опор (видна только им).

    Модель только разбирает утверждение и выписывает цитаты; решает код. Обоснование генератора проверке
    не показывается — это уговоры, а не опоры (с ним проверка пропускала 16 из 28 испорченных гипотез).

    Третье значение — пометки, которые гипотезу не отклоняют (почти все статьи о рейтингах и о
    зарубежных данных), но должны быть написаны в ней самой: "proxy" — чем опоры заменяют объём
    ESG-инвестиций (утверждение о нём, опоры — о рейтинге, раскрытии или практиках); "abroad" — числа
    из опор, если утверждение о России, а связь получена на зарубежных данных (список, может быть пуст).

    Четвёртое — отклонена только за знак, которого опоры не называют (но и не опровергают): такую
    гипотезу можно переписать без знака (_unsign)."""
    texts = [f"{it.get('fact', '')} {it['text'][:700]}".strip() for it in cited]
    refs = "\n".join(f"[{i}] {t} («{it['title']}»)" for i, (t, it) in enumerate(zip(texts, cited, strict=True), start=1))
    prompt = f"ЗАДАНИЕ: {target['title']}\n{target['content'][:1200]}\n\nУТВЕРЖДЕНИЕ: {h['statement']}\n\nОПОРЫ:\n{refs}"
    try:
        d = ask_json(prompt, 500, CHECK_SYSTEM, CHECK_SCHEMA, temperature=0)
    except (ValueError, TimeoutError, URLError, OSError):
        return False, "проверка опор не ответила", {}, False
    failed = []
    task = d["task_level"]
    if task != "другое" and d["level"] != task:
        failed.append(f"не о результате задания ({d['level']}, а задание — {task})")
    if task != "другое" and d["refs_level"] != task:
        failed.append(f"опоры о другом уровне ({d['refs_level']}, а задание — {task})")
    if not _quoted(d["link_quote"], [t for t in texts if _is_prose(t)]):
        failed.append("в опорах нет связи этого фактора с этим показателем"
                      + (" (цитата не дословная или из таблицы)" if d["link_quote"] else ""))
    direction = d["direction"]
    # знак — и по словам утверждения и названия: модель охотно пишет «связь без знака», чтобы не искать
    # цитату, а в названии оставляет «повышают» при «связан» в утверждении
    if direction not in ("рост", "снижение") and SIGNED.search(f"{h['title']} {h['statement']}"):
        direction = "снижение" if d["refs_direction"] == "снижение" else "рост"
    sign_only = False
    if direction in ("рост", "снижение") and (d["refs_direction"] != direction
                                             or not _quoted(d["direction_quote"], texts)):
        failed.append(f"направление «{direction}» опоры не подтверждают" + (
            f" (в опорах: {d['refs_direction']})" if d["refs_direction"] != direction else " (нет цитаты)"))
        # опровергнуть знак может только цитата с другим знаком; без неё знак просто не установлен
        sign_only = not (d["refs_direction"] in ("рост", "снижение") and _quoted(d["direction_quote"], texts))
    # четырёхзначное — календарный год («в 2021 году»), а не срок
    extra = {y for y in _years(h["statement"]) - _years(target["content"]) - set().union(*map(_years, texts))
             if len(y) < 4}
    if extra:
        failed.append(f"горизонт {', '.join(sorted(extra, key=int))} лет — ни в задании, ни в опорах")
    comment = str(d.get("comment") or "")[:200]
    if failed:
        return False, "; ".join(failed) + (f" — {comment}" if comment else ""), {}, sign_only and len(failed) == 1
    marks: dict[str, Any] = {}
    if (d["factor_kind"] == INVESTMENT and d["refs_factor_kind"] in PROXY_SHORT
            and not PROXY_SAID.search(h["statement"])):
        marks["proxy"] = d["refs_factor_kind"]
    if d.get("link_scope") == ABROAD and RUSSIA.search(h["statement"]):
        # числа утверждения, взятые из опор: для России это ориентир, а не ожидаемое значение
        found = dict.fromkeys(m.group(0).replace(" ", "") for m in re.finditer(r"\d+(?:[.,]\d+)?\s*%?",
                                                                                  h["statement"]))
        figures = [f for f in found if (n := f.rstrip("%")) not in _years(h["statement"]) and any(
            re.search(rf"(?<![\d.,]){re.escape(n)}(?![\d])", t) for t in texts)]
        if figures or not ABROAD_SAID.search(h["statement"]):
            marks["abroad"] = figures
    return True, f"связь в опорах: «{d['link_quote'][:200]}»" + (f"; {comment}" if comment else ""), marks, False


UNSIGN_SYSTEM = """Перепиши название и утверждение гипотезы без знака связи: вместо «повышает», «улучшает»,
«снижает», «положительно влияет», «рост» — «связан с». Фактор, показатель, горизонт и данные оставь как
есть, ничего не добавляй. Знак покажет расчёт. Ответ — только JSON {"title": "…", "statement": "…"}."""
UNSIGN_SCHEMA = {"type": "object", "required": ["title", "statement"], "properties": {"title": _S, "statement": _S}}


def _unsign(h: dict[str, Any]) -> dict[str, Any] | None:
    """Правило 10 — кодом: модель пишет «положительно», когда опоры говорят только, что связь есть.
    Переписанное без знака проверяется заново; если знак остался — None (гипотеза отклоняется)."""
    try:
        d = ask_json(f"НАЗВАНИЕ: {h['title']}\nУТВЕРЖДЕНИЕ: {h['statement']}", 400, UNSIGN_SYSTEM, UNSIGN_SCHEMA,
                     temperature=0)
    except (ValueError, TimeoutError, URLError, OSError):
        return None
    title, statement = str(d.get("title") or "").strip(), str(d.get("statement") or "").strip()
    if len(title) < 5 or len(statement) < 10 or SIGNED.search(f"{title} {statement}") or CJK.search(
            f"{title} {statement}"):
        return None
    return {**h, "title": title, "statement": statement}


def _review(h: dict[str, Any], cited: list[dict[str, Any]],
            target: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Проверка опор с исправлениями кодом: знак, которого опоры не называют, убирается (правило 10),
    замена объёма инвестиций рейтингом (правило 9) и зарубежные данные о России (правило 8)
    помечаются. Возвращает (гипотеза или None, комментарий)."""
    if CJK.search(f"{h['title']} {h['statement']} {h['rationale']}"):
        return None, "в тексте иероглифы — модель сбилась с языка"
    ok, comment, marks, sign_only = _verify(h, cited, target)
    if not ok and sign_only:
        fixed = _unsign(h)
        if fixed is not None:
            ok, again, marks, _ = _verify(fixed, cited, target)
            if ok:
                h, comment = fixed, f"знак убран — опоры его не называют, покажет расчёт; {again}"
            else:
                comment = f"{comment}; без знака: {again}"
    return (_mark(h, marks), comment) if ok else (None, comment)


def _mark(h: dict[str, Any], marks: dict[str, Any]) -> dict[str, Any]:
    """Правила 8 и 9 — кодом: модель пишет «объём ESG-инвестиций», когда опоры об ESG-рейтинге, и
    переносит на российские агентства числа зарубежных провайдеров, даже если её об этом прямо
    просят. Пометка — в названии (видна в списке) и в утверждении (что проверять)."""
    title, statement = h["title"], h["statement"].rstrip()
    if "proxy" in marks:
        title += f" (по {PROXY_SHORT[marks['proxy']]})"
        statement += (f" Мера фактора — {marks['proxy']} как замена объёма ESG-инвестиций: об объёме "
                      "вложений в опорах данных нет.")
    if "abroad" in marks:
        title += " (по зарубежным данным)"
        statement += " Связь в опорах получена на зарубежных данных; для России её надо проверить"
        figures = ", ".join(marks["abroad"])
        statement += (f": {figures} — ориентир для сравнения, а не ожидаемое значение." if figures else ".")
    if not marks:
        return h
    return {**h, "title": title[:300], "statement": statement}


def _numbers(value: Any, top: int) -> list[int]:
    """Номера опор из ответа модели: [1, 3], ["1", "3"], "1, 3" — только существующие."""
    raw = value if isinstance(value, list) else re.findall(r"\d+", str(value or ""))
    out = []
    for x in raw:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= top and n not in out:
            out.append(n)
    return out


def job_hypotheses(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    context = ctx["platform"].post("context")[1]
    out: list[dict[str, Any]] = []
    skipped: list[str] = []
    answers: dict[str, str] = {}
    rejected: list[dict[str, str]] = []  # отброшенные проверкой опор — в итог задачи
    own = _own_reports(ctx["kbrag_token"])
    asked = failed = 0
    for target in context["targets"]:
        if target["pending_qwen"] >= context["limits"]["pending"]:
            skipped.append(f"{target['number']}: ждут рецензии {target['pending_qwen']}")
            continue
        # гипотезы этого прохода по другим заданиям — тоже «уже есть»: без повторов между заданиями
        target = {**target, "existing": target["existing"] + [
            {"code": f"новая ({x['node']})", "title": x["title"], "status": "предложена сейчас"} for x in out]}
        items = _evidence(target, ctx["kbrag_token"], own)
        if not items:
            skipped.append(f"{target['number']}: в базе нет опор")
            continue
        asked += 1
        try:
            answer = json.dumps(ask_json(_prompt(target, context, items), 1800, HYP_SYSTEM, HYP_SCHEMA),
                                ensure_ascii=False)
        except (ValueError, TimeoutError, URLError, OSError) as exc:
            # сбой по одному заданию не должен стоить гипотез по остальным
            failed += 1
            log(f"  {target['number']}: модель не ответила ({exc})")
            skipped.append(f"{target['number']}: модель не ответила ({exc})"[:300])
            continue
        answers[target["number"]] = answer[:4000]
        before = len(out)
        for item in _parse(answer)[: context["limits"]["per_run"]]:
            nums = _numbers(item.get("fragments"), len(items))
            if not nums:
                continue  # без опоры из найденного — не гипотеза
            h = {k: str(item.get(k) or "") for k in ("title", "statement", "rationale", "dataset", "method",
                                                     "data_needed")}
            checked, comment = _review(h, [items[n - 1] for n in nums], target)
            if checked is None:
                rejected.append({"node": target["number"], "title": h["title"], "why": comment})
                continue
            h = checked
            h["rationale"] = f"{h['rationale']}\nПроверка опор (Qwen): {comment}".strip()
            out.append({**h, "node": target["number"], "refs": [_ref(items[n - 1]) for n in nums]})
        facts = sum(1 for it in items if it["kind"] == "fact")
        log(f"  {target['number']}: опор {len(items)} (фактов {facts}), гипотез {len(out) - before}")
        if len(out) == before:
            skipped.append(f"{target['number']}: модель не нашла обоснованной гипотезы")
    if asked and failed == asked:
        raise RuntimeError(f"модель не ответила ни по одному из заданий ({failed}): {skipped[-1]}")
    # ответы модели — в журнал задачи: по ним видно, почему по заданию ничего не предложено
    (ctx["logs"] / f"qwen-hypotheses-{job['id']}.json").write_text(
        json.dumps(answers, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"hypotheses": out, "skipped": skipped, "rejected": rejected, "targets": len(context["targets"])}


EXP_SYSTEM = """Ты — исследователь НИЦ ИИ (Университет «Дубна») и Лаборатории технологий ИНС для управления бизнесом в формате ESG. Гипотезу приняли к проверке; предложи
эксперимент, который её подтвердит или опровергнет.

Правила:
1. "method" — ключ метода ТОЛЬКО из библиотеки. Повтор (scope replication) — только на своём датасете и только
   если гипотеза о воспроизведении этой работы: новых показателей он не считает.
   Если ни один метод не проверяет гипотезу, верни "method": "" и в "rationale" опиши, какой метод нужен.
2. "snapshot_id" — номер среза из списка, на котором есть нужные показатели (смотри числовые столбцы);
   нет подходящего — 0, и в "rationale" напиши, каких данных не хватает.
3. "params" — параметры выбранного метода: имена столбцов пиши ТОЧНО как в списке столбцов среза;
   числа — в границах метода. Целевой показатель не может быть признаком.
4. "setup" — 3–6 коротких шагов протокола, с учётом раздела методики «Проверка моделей» (отложенная
   выборка, разбиения, плацебо, сравнение с простым прогнозом, контроль размера и отрасли).
5. "expected" — какой результат подтвердит гипотезу и какой опровергнет (с числами: знак, порог R² или ρ).
6. Пиши по-русски; имена столбцов — как в данных.
Ответ — только JSON по схеме."""

EXP_SCHEMA = {"type": "object", "required": ["title", "method", "snapshot_id", "params", "setup", "expected",
                                             "rationale"], "properties": {
    "title": _S, "method": _S, "snapshot_id": _I, "params": {"type": "object"},
    "setup": {"type": "array", "items": _S, "maxItems": 6}, "expected": _S, "rationale": _S}}


def _exp_prompt(c: dict[str, Any]) -> str:
    h = c["hypothesis"]
    refs = "\n".join(f"- «{r['quote'][:400]}» («{r['title']}»)" for r in h["refs"]) or "- нет"
    task = f"{c['task']['number']} {c['task']['title']}: {c['task']['content'][:900]}" if c["task"] else "не указано"
    sections = "\n".join(f"- {s['number']} {s['title']}: {s['content'][:600]}" for s in c["sections"]) or "- нет"
    methods = "\n".join(
        f"- {m['key']} ({m['scope']}{', датасет ' + m['dataset'] if m['dataset'] else ''}): {m['title']}. "
        f"{m['description']} Параметры: " + "; ".join(
            f"{p['name']} ({p['kind']}{', ' + str(p['min']) + '…' + str(p['max']) if p['kind'] == 'int' else ''}"
            f"{', по умолчанию ' + json.dumps(p['default'], ensure_ascii=False) if p['default'] not in (None, '', []) else ''})"
            for p in m["params"]) for m in c["methods"])
    snaps = "\n".join(
        f"- срез {s['id']}: {s['dataset']} «{s['title']}», версия {s['version']}, строк {s['rows'] or '?'}. "
        f"{s['description'][:300]} "
        + (("Книга Excel — в params укажи sheet (лист), столбцы — с этого листа. Листы: " + "; ".join(
            f"«{sh['name']}» — числовые столбцы: {', '.join(sh['numeric_columns']) or 'нет'}" for sh in s["sheets"]))
           if s.get("sheets") else
           "Числовые столбцы: " + ", ".join(s["numeric_columns"]) if s["table"]
           else "файл не таблица (CSV или Excel) — общие методы его не читают")
        for s in c["snapshots"])
    return (f"ГИПОТЕЗА {h['code']}: {h['title']}\n{h['statement']}\nОбоснование: {h['rationale'][:800]}\n"
            f"Qwen ранее предлагала проверить: {json.dumps(h['suggested'], ensure_ascii=False)}\n\n"
            f"ОПОРЫ ГИПОТЕЗЫ:\n{refs}\n\nЗАДАНИЕ МЕТОДИКИ: {task}\n\nРАЗДЕЛЫ МЕТОДИКИ:\n{sections}\n\n"
            f"БИБЛИОТЕКА МЕТОДОВ:\n{methods}\n\nСРЕЗЫ ДАННЫХ:\n{snaps}\n\nПредложи эксперимент по правилам.")


def job_experiment(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Предложение эксперимента по принятой гипотезе: метод, срез, параметры, протокол."""
    code = str(job["payload"].get("hypothesis") or "")
    c = ctx["platform"].post("experiment-context", {"hypothesis": code})[1]
    proposal = ask_json(_exp_prompt(c), 1500, EXP_SYSTEM, EXP_SCHEMA)
    if not proposal.get("snapshot_id"):
        proposal["snapshot_id"] = None
    log(f"  {code}: {proposal.get('method') or 'без метода'} на срезе {proposal.get('snapshot_id')}, "
        f"параметры {json.dumps(proposal.get('params'), ensure_ascii=False)[:200]}")
    return {"proposal": proposal}


REPORT_SYSTEM = """Ты — исследователь НИЦ ИИ (Университет «Дубна») и Лаборатории технологий ИНС для управления бизнесом в формате ESG. Эксперимент посчитан; напиши текст
отчёта по фактам расчёта ниже.

Правила:
1. Только факты ниже. НЕ придумывай чисел: любое число в тексте должно быть в ключевых цифрах, графиках
   или итогах расчёта. Можно округлять до двух знаков.
2. "verdict": confirmed — гипотеза подтверждена, rejected — отклонена, inconclusive — неоднозначно. Если
   есть критерий, заданный до расчёта, — суди по нему. Без критерия: гипотеза утверждает связь или
   согласованность — значит, она подтверждена, только если эффект значим (интервал не задевает ноль,
   R² выше плацебо); слабый и незначимый эффект — rejected. Если исследователи уже записали вывод
   эксперимента, не противоречь ему без оснований из цифр. Отрицательный результат — нормальный исход,
   его не смягчай. "summary" и "verdict_reason" не противоречат "verdict": не пиши «подтверждена
   частично», если вердикт не confirmed.
3. "interpretation" — 3–5 пунктов: что показали цифры и почему так могло получиться (со ссылкой на
   опоры гипотезы, если они объясняют). Статью из опор можно назвать только как «согласуется с»: не пиши,
   что эксперимент «подтверждает» механизм из статьи, если этот механизм в расчёте не проверялся.
4. "meaning" — что результат значит для задания методики (вход, выход, горизонт задания).
5. "methodology" — предложение изменить методику (правило, порог, выбор данных или показателя, граница
   применимости), только если главный результат это оправдывает; иначе "". Планы следующих
   экспериментов (больше данных, срезов) — не методика, они в "next".
6. "limitations" — 2–4 пункта: выборка, данные, метод. "next" — 2–4 следующих шага.
7. Пиши по-русски, коротко и точно; названия показателей — как в данных.
Ответ — только JSON по схеме."""

REPORT_SCHEMA = {"type": "object", "required": ["summary", "verdict", "verdict_reason", "interpretation", "meaning",
                                                "methodology", "limitations", "next"], "properties": {
    "summary": _S, "verdict": {"type": "string", "enum": ["confirmed", "rejected", "inconclusive"]},
    "verdict_reason": _S, "interpretation": {"type": "array", "items": _S, "maxItems": 6}, "meaning": _S,
    "methodology": _S, "limitations": {"type": "array", "items": _S, "maxItems": 5},
    "next": {"type": "array", "items": _S, "maxItems": 5}}}


OUTCOME = {"confirmed": "гипотеза подтверждена", "rejected": "гипотеза отклонена", "inconclusive": "неоднозначно"}


def _report_prompt(c: dict[str, Any]) -> str:
    f = c["facts"]
    e, run, h = f.get("experiment", {}), f.get("run", {}), f.get("hypothesis") or {}
    kpis = "\n".join(f"- {k.get('label')}: {k.get('value')} ({k.get('note', '')}{'; было ' + k['was'] if k.get('was') else ''})"
                     for k in f.get("kpis") or []) or "- нет"
    charts = []
    for ch in f.get("charts") or []:
        if ch.get("kind") == "ranges":
            data = "; ".join(f"{r['name']}: среднее {r['mean']}, от {r['min']} до {r['max']}" for r in ch.get("rows") or [])
        else:
            data = "; ".join(f"{s['name']}: " + ", ".join(f"{c}={v}" for c, v in zip(ch.get("categories") or [], s["values"]))
                             for s in ch.get("series") or [])
        charts.append(f"- «{ch.get('title')}» ({ch.get('subtitle', '')}): {data}. Подпись: {ch.get('interpretation', '')}")
    task = "\n".join(f"- {t['number']} {t['title']}: {t['content'][:600]}" for t in c["task"]) or "- не указано"
    sections = "\n".join(f"- {s['number']} {s['title']}: {s['content'][:400]}" for s in c["sections"]) or "- нет"
    refs = "\n".join(f"- «{r['quote'][:300]}» («{r['title']}»)" for r in c["refs"]) or "- нет"
    return (f"ЭКСПЕРИМЕНТ {e.get('code')}: {e.get('title')}\nГипотеза: {h.get('statement') or e.get('hypothesis')}\n"
            f"Критерий до расчёта: {f.get('expected') or 'не задан'}\n"
            f"Метод: {run.get('template_title') or e.get('method')}; параметры: {json.dumps(run.get('params') or {}, ensure_ascii=False)}\n"
            f"Данные: {run.get('dataset')} срез {run.get('snapshot_version')}, строк {run.get('rows')}\n"
            f"Протокол: {'; '.join(e.get('setup') or []) or '—'}\n"
            f"Ограничения, записанные в эксперименте: {'; '.join(e.get('limitations') or []) or '—'}\n"
            f"Вывод исследователей, записанный в эксперименте: {e.get('conclusion') or 'не записан'} "
            f"(итог: {OUTCOME.get(e.get('outcome') or '', 'не указан')})\n\n"
            f"КЛЮЧЕВЫЕ ЦИФРЫ:\n{kpis}\n\nГРАФИКИ (значения):\n" + ("\n".join(charts) or "- нет") +
            f"\n\nИТОГИ РАСЧЁТА: {json.dumps(run.get('summary') or {}, ensure_ascii=False)[:1500]}\n\n"
            f"ЗАДАНИЕ МЕТОДИКИ (от направления к заданию):\n{task}\n\nРАЗДЕЛЫ МЕТОДИКИ:\n{sections}\n\n"
            f"ОПОРЫ ГИПОТЕЗЫ:\n{refs}\n\nНапиши отчёт по правилам.")


def job_report(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Текст отчёта по фактам расчёта; цифры и графики платформа берёт из run.json сама."""
    rid = int(job["payload"].get("report") or 0)
    c = ctx["platform"].post("report-context", {"report": rid})[1]
    sections = ask_json(_report_prompt(c), 2200, REPORT_SYSTEM, REPORT_SCHEMA)
    log(f"  отчёт №{rid}: вердикт {sections.get('verdict')}, пунктов интерпретации {len(sections.get('interpretation') or [])}")
    return {"sections": sections}


CR_SYSTEM = """Ты — методолог НИЦ ИИ (Университет «Дубна») и Лаборатории технологий ИНС для управления бизнесом в формате ESG. Отчёт об эксперименте одобрен рецензентом.
Реши, нужно ли по нему менять методику, и если нужно — подготовь черновик предложения изменения (CR).

Правила:
1. "decision": "change" — только если ГЛАВНЫЙ результат (вердикт и резюме) что-то меняет в методике:
   правило, порог, выбор данных или показателя, ограничение применимости. Отрицательный результат тоже
   может менять методику (например, нельзя опираться на один источник). «Предложение для методики из
   отчёта» одобрено рецензентом — опирайся на него; но если там план следующего эксперимента (больше
   данных, срезов), а не правило, — переведи в правило главный вывод или ответь "none". Ограничения и
   «что дальше» — не повод для CR. То, что уже сделано в протоколе эксперимента, не предлагай как
   новое. Если результат ничего не меняет или такое изменение уже есть в открытых CR — "none" и
   коротко "reason".
2. "section" — номер узла ТОЛЬКО из списка УЗЛЫ ниже, буквы кириллицей (Н2, Н1.В1.З1). Два действия:
   - "add" — новый РАЗДЕЛ (правило) под узлом: "new_kind": "section", заголовок — "new_title". Так —
     почти всегда: направления, варианты и задания не трогай, их описания правят люди.
   - "edit" — дополнить существующий РАЗДЕЛ (вид «раздел»), если правило относится к нему;
     "new_kind" и "new_title" — "".
   Предпочитай самое узкое место: узел эксперимента, а не общие разделы.
3. "proposed_content" — только НОВЫЙ текст: при add — текст раздела, при edit — что дописать к разделу
   (прежний текст не повторяй, платформа допишет). Пиши как правило методики, что делать: «Согласованность
   … проверять …», «Не опираться на …». Без заголовков, номеров и пересказа эксперимента — он в "description".
4. "title" — коротко, что меняется. "description" — почему: что показал эксперимент, с ключевыми
   числами из отчёта (только из него), и чем ограничен вывод (выборка, срез).
5. Не обещай больше, чем показал эксперимент: незначимый результат не доказывает отсутствие связи.
6. Пиши по-русски, коротко и точно. Ответ — только JSON по схеме."""

CR_SCHEMA = {"type": "object", "required": ["decision", "reason", "section", "action", "new_kind", "new_title",
                                            "title", "description", "proposed_content"], "properties": {
    "decision": {"type": "string", "enum": ["change", "none"]}, "reason": _S, "section": _S,
    "action": {"type": "string", "enum": ["edit", "add"]},
    "new_kind": {"type": "string", "enum": ["", "section"]}, "new_title": _S,
    "title": _S, "description": _S, "proposed_content": _S}}
KIND_RU = {"direction": "направление", "variant": "вариант", "task": "задание", "section": "раздел"}


def _cr_prompt(c: dict[str, Any]) -> str:
    s, e = c["sections"], c["experiment"]
    lst = lambda xs: "; ".join(xs or []) or "—"  # noqa: E731
    kpis = "\n".join(f"- {k.get('label')}: {k.get('value')} ({k.get('note', '')})" for k in c.get("kpis") or []) or "- нет"
    nodes = "\n".join(
        f"- {t['number']} ({KIND_RU.get(t['kind'], t['kind'])}{', в ' + t['parent'] if t['parent'] else ''}) «{t['title']}»; "
        f"можно добавить: {', '.join(KIND_RU[k] for k in t['can_add']) or 'ничего'}; "
        f"открытые CR: {lst(t['open_crs'])}\n  Текст: {t['content'] or '(пусто)'}" for t in c["targets"]) or "- нет"
    return (f"ОТЧЁТ {e.get('code')} v{c['version']}: {e.get('title')}\nГипотеза: {e.get('hypothesis')}\n"
            f"Задание методики эксперимента: {e.get('node') or 'не указано'}\n"
            f"Протокол (уже сделано): {lst(e.get('setup'))}\n"
            f"Резюме: {s.get('summary', '')}\nВердикт: {OUTCOME.get(str(s.get('verdict')), '—')} — {s.get('verdict_reason', '')}\n"
            f"Интерпретация: {lst(s.get('interpretation'))}\nЗначение для задания: {s.get('meaning') or '—'}\n"
            f"Предложение для методики из отчёта: {s.get('methodology') or '—'}\n"
            f"Ограничения: {lst(s.get('limitations'))}\n\nКЛЮЧЕВЫЕ ЦИФРЫ:\n{kpis}\n\n"
            f"УЗЛЫ МЕТОДИКИ, КОТОРЫЕ МОЖНО МЕНЯТЬ:\n{nodes}\n\nРеши по правилам.")


def job_cr(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Черновик CR по одобренному отчёту; проверяет и создаёт CR платформа."""
    rid = int(job["payload"].get("report") or 0)
    c = ctx["platform"].post("cr-context", {"report": rid})[1]
    out = ask_json(_cr_prompt(c), 2500, CR_SYSTEM, CR_SCHEMA)
    log(f"  CR по отчёту №{rid}: {out.get('decision')} {out.get('action')} {out.get('section')} «{out.get('title')}»")
    return out


# --- таблицы статей → черновики датасетов ---

TABLE_SYSTEM = """Ты — исследователь лаборатории ESG. Тебе дают таблицу из научной статьи, уже разобранную
кодом в строки и столбцы. Реши, НАБЛЮДЕНИЯ ли это — исходные данные, где строка — один объект или
период (компания, регион, страна, год, индекс за год) и столбцы — его показатели, — на которых можно
что-то посчитать. НЕ наблюдения: результаты расчёта авторов (коэффициенты регрессий, корреляции,
описательная статистика, веса AHP, VIF, нагрузки факторов, метрики качества моделей), распределение
выборки по отраслям или странам, словари переменных, план или бюджет одной компании.
Поля:
- "row_is": что такое одна строка таблицы (по-русски, коротко);
- "observations": true — наблюдения, false — нет;
- "why": одной фразой — почему;
- "title": название будущего датасета по-русски, до 120 знаков (что, по каким объектам, за какие годы);
- "description": 2–4 предложения по-русски: что такое строка, что значат столбцы (единицы, шкала:
  ранг, балл, %, тыс. руб.), откуда данные по словам статьи. Ничего не додумывай.
Ответ — только JSON по схеме."""
TABLE_SCHEMA = {"type": "object", "required": ["row_is", "observations", "why", "title", "description"],
                "properties": {"row_is": _S, "observations": {"type": "boolean"}, "why": _S, "title": _S,
                               "description": _S}}


def _cells(rows: list[list[Any]], limit: int) -> str:
    return "\n".join(f"{i}. " + " | ".join("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))
                                            for v in r) for i, r in enumerate(rows[:limit], start=1))


def _describe(d: dict[str, Any]) -> str:
    """Описание датасета: что такое строка — один раз (модель часто сама начинает с «Строка — …»)."""
    text = str(d.get("description") or "").strip()
    row = str(d.get("row_is") or "").strip().rstrip(".")
    return text if not row or text.lower().startswith("строка") else f"Строка — {row}. {text}".strip()


def _doi(url: str) -> str:
    m = re.search(r"10\.\d{4,9}/\S+", url or "")
    return m.group(0).rstrip(".,;)") if m else ""


def job_tables(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Таблицы статей ветки esg: разбор кодом (tables.py), отбор наблюдений и описание — Qwen."""
    import tables as T  # рядом с worker.py; только stdlib

    want = str(job["payload"].get("doc_id") or "")
    docs = kbrag_get("documents", {"kb": "esg"}, ctx["kbrag_token"], timeout_s=60).get("documents") or []
    docs = [d for d in docs if not want or d.get("doc_id") == want]
    known = {(d, n) for d, n in ctx["platform"].post("tables-context")[1].get("known") or []}
    acquired = Path(ctx["kbrag"]) / ".local" / "acquired"
    drafts: list[dict[str, Any]] = []
    skipped: list[str] = []
    for meta in docs:
        doc_id = str(meta.get("doc_id") or "")
        path = acquired / f"{doc_id}.docling.json"
        if not path.exists():
            skipped.append(f"{doc_id}: нет разметки docling")
            continue
        for x in T.tables(json.loads(path.read_text(encoding="utf-8"))):
            if (doc_id, x["number"]) in known:
                continue
            if not x["data"]:
                continue  # код уже видит, что это не наблюдения
            t = x["table"]
            prompt = (f"СТАТЬЯ: {meta.get('title', '')}\nТАБЛИЦА {x['number']}"
                      + (f" (с. {x['page']})" if x["page"] else "") + f": {x['caption'] or 'без подписи'}\n"
                      f"ЧТО СДЕЛАЛ КОД: {'; '.join(t.notes) or 'ничего'}\n"
                      f"СТОЛБЦЫ: {' | '.join(t.columns)}\nСТРОК: {len(t.rows)}\nПЕРВЫЕ СТРОКИ:\n{_cells(t.rows, 12)}")
            try:
                d = ask_json(prompt, 700, TABLE_SYSTEM, TABLE_SCHEMA)
            except ValueError as exc:
                skipped.append(f"{doc_id} т{x['number']}: модель не ответила ({exc})")
                continue
            if not d.get("observations"):
                skipped.append(f"{doc_id} т{x['number']}: не наблюдения — {d.get('why', '')}")
                continue
            drafts.append({"doc_id": doc_id, "kb_path": "esg", "article_title": meta.get("title", ""),
                           "doi": _doi(str(meta.get("url") or "")), "table_number": x["number"],
                           "page": x["page"], "caption": x["caption"], "title": d.get("title", ""),
                           "description": _describe(d),
                           "columns": t.columns, "rows": t.rows[:5000], "notes": t.notes})
            log(f"  {doc_id} т{x['number']}: черновик «{d.get('title', '')}» ({len(t.rows)}×{len(t.columns)})")
    return {"drafts": drafts, "skipped": skipped[:200], "docs": len(docs)}


OPS = ["rename", "drop_columns", "keep_columns", "drop_rows", "drop_rows_where", "keep_rows_where", "set_cell",
       "to_number", "scale", "add_column", "sort", "transpose"]
EDIT_SYSTEM = """Ты правишь таблицу данных по команде исследователя. Код ты не пишешь: ответ — список
операций, их применит платформа по порядку. Операции:
- {"op": "rename", "column": имя, "to": новое имя}
- {"op": "drop_columns", "columns": [имена]} / {"op": "keep_columns", "columns": [имена по порядку]}
- {"op": "drop_rows", "rows": [номера строк, как в таблице ниже, с 1]}
- {"op": "drop_rows_where" | "keep_rows_where", "column": имя, "test": "empty"|"equals"|"contains"|"less"|"greater",
  "value": значение} — убрать / оставить строки, где условие верно
- {"op": "set_cell", "rows": [номер строки], "column": имя, "value": новое значение}
- {"op": "to_number", "column": имя} — текст в числа («1 234,5» → 1234,5; не число — пропуск)
- {"op": "scale", "column": имя, "factor": число} — умножить (тыс. руб. → руб.: 1000)
- {"op": "add_column", "name": имя, "value": значение для всех строк}
- {"op": "sort", "column": имя, "descending": true|false}
- {"op": "transpose"} — строки станут столбцами (первый столбец — имена новых столбцов)
Имена столбцов пиши ТОЧНО как в таблице. Делай только то, что просят; не можешь — пустой список ops и
в "explanation" — почему. "explanation" — одной фразой по-русски, что сделано.
Ответ — только JSON по схеме."""
EDIT_SCHEMA = {"type": "object", "required": ["explanation", "ops"], "properties": {
    "explanation": _S, "ops": {"type": "array", "maxItems": 20, "items": {"type": "object", "required": ["op"],
        "properties": {"op": {"type": "string", "enum": OPS}, "column": _S, "to": _S,
                       "columns": {"type": "array", "items": _S}, "rows": {"type": "array", "items": _I},
                       "test": {"type": "string", "enum": ["empty", "equals", "contains", "less", "greater"]},
                       "value": _S, "factor": {"type": "number"}, "name": _S, "descending": {"type": "boolean"}}}}}}


def job_table_edit(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Команда словами по черновику → операции; применяет и проверяет их платформа."""
    did = int(job["payload"].get("draft") or 0)
    command = str(job["payload"].get("command") or "")
    c = ctx["platform"].post("draft-context", {"draft": did, "command": command})[1]
    prompt = (f"ТАБЛИЦА: {c.get('title', '')} (из статьи «{c.get('article_title', '')}», подпись: "
              f"{c.get('caption', '') or 'нет'})\nОПИСАНИЕ: {c.get('description', '')}\n"
              f"СТОЛБЦЫ: {' | '.join(c.get('columns') or [])}\nСТРОК: {c.get('row_count')}\n"
              f"СТРОКИ (первые {min(40, c.get('row_count') or 0)}):\n{_cells(c.get('rows') or [], 40)}\n"
              f"ПРЕЖНИЕ ПРАВКИ: {'; '.join(c.get('history') or []) or 'нет'}\n\nКОМАНДА: {command}")
    out = ask_json(prompt, 900, EDIT_SYSTEM, EDIT_SCHEMA)
    ops = []
    for op in out.get("ops") or []:
        op = {k: v for k, v in op.items() if v not in (None, "", [])}
        if op.get("op") in ("drop_rows", "set_cell") and isinstance(op.get("rows"), list):
            nums = [n - 1 for n in op["rows"] if isinstance(n, int)]  # в подсказке строки с 1
            if op["op"] == "set_cell":
                op["row"] = nums[0] if nums else -1
                op.pop("rows")
            else:
                op["rows"] = nums
        ops.append(op)
    log(f"  черновик №{did}: «{command}» → {len(ops)} операций: {out.get('explanation', '')}")
    return {"ops": ops, "explanation": out.get("explanation", ""), "draft": did}


HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "ping": job_ping,
    "graph": job_graph,
    "hypotheses": job_hypotheses,
    "experiment": job_experiment,
    "report": job_report,
    "cr": job_cr,
    "tables": job_tables,
    "table_edit": job_table_edit,
}


def describe(kind: str, result: dict[str, Any]) -> str:
    if kind == "graph":
        if "facts_accepted" in result:
            return (f"Пройдено фрагментов: {result.get('fragments', '?')}; фактов принято "
                    f"{result['facts_accepted']}, отброшено проверкой {result['facts_rejected']}")
        return "Новых фрагментов нет — граф уже полный"
    if kind == "ping":
        return f"Модель ответила за {result.get('seconds')} с: {result.get('answer')}"
    if kind == "experiment":
        return "Предложение эксперимента передано платформе"
    if kind == "report":
        return "Текст отчёта передан платформе"
    if kind == "cr":
        return ("Черновик CR передан платформе" if result.get("decision") == "change"
                else f"Менять методику не нужно: {result.get('reason', '')}")
    if kind == "tables":
        return (f"Статей {result.get('docs', 0)}: таблиц-наблюдений {len(result.get('drafts') or [])} "
                "(черновики создаст платформа)")
    if kind == "table_edit":
        return f"Операций {len(result.get('ops') or [])}: {result.get('explanation', '')}"
    if kind == "hypotheses":
        return f"Qwen предложила {len(result.get('hypotheses') or [])} (платформа проверит опоры)"
    return ""


def main() -> int:
    env = read_env(DEPLOY / ".env")
    ap = argparse.ArgumentParser(description="Обработчик очереди задач Qwen")
    ap.add_argument("--platform", default=env.get("PLATFORM_URL") or f"https://127.0.0.1:{env.get('HTTP_PORT', '8080')}")
    ap.add_argument("--ca", type=Path, default=DEPLOY / "certs" / "lab-root-ca.crt")
    ap.add_argument("--kbrag", type=Path, default=Path(os.environ.get("KBRAG_HOME", r"C:\Users\Grisha\KBRAG")))
    ap.add_argument("--idle-min", type=float, default=10)
    ap.add_argument("--once", action="store_true", help="разобрать очередь, выключить модель и выйти")
    args = ap.parse_args()
    token = os.environ.get("QWEN_TOKEN") or env.get("QWEN_TOKEN", "")
    if not token:
        log("нет QWEN_TOKEN в deploy/.env — выхожу")
        return 1
    platform = Platform(args.platform, token, args.ca)
    logs = DEPLOY / "windows" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    model = Model(args.kbrag, logs / "qwen_started_by_worker.flag")
    ctx = {"kbrag": args.kbrag, "logs": logs, "platform": platform,
           "kbrag_token": os.environ.get("KBRAG_TOKEN") or env.get("KBRAG_TOKEN", "")}
    current: dict[str, Any] = {}

    def beat() -> None:
        used, total = gpu()
        detail = model.detail or (f"задача №{current['id']} ({current['kind']})" if current else "")
        try:
            platform.post("heartbeat", {"model": model.state, "detail": detail,
                                        "gpu_used_mb": used, "gpu_total_mb": total})
        except (RuntimeError, URLError, OSError) as exc:
            log(f"отметка не прошла: {exc}")

    def beat_forever() -> None:
        while True:
            beat()
            time.sleep(BEAT_S)

    threading.Thread(target=beat_forever, daemon=True).start()
    log(f"обработчик Qwen: {args.platform}, KBRAG {args.kbrag}, выключение после {args.idle_min} мин простоя")
    try:
        log(f"вернул в очередь недоделанные: {platform.post('requeue')[1]['requeued']}")
    except (RuntimeError, URLError, OSError) as exc:
        log(f"платформа недоступна: {exc}")
    idle_since = time.time()
    while True:
        try:
            queued = platform.post("peek")[1]["queued"]
        except (RuntimeError, URLError, OSError, TypeError) as exc:
            log(f"платформа недоступна: {exc}")
            queued = 0
        if queued and model.start():
            while True:
                try:
                    code, job = platform.post("next")
                except (RuntimeError, URLError, OSError) as exc:
                    log(f"платформа недоступна: {exc}")
                    break
                if code != 200 or not job:
                    break
                current.update(job)
                log(f"задача №{job['id']}: {job['kind']} {job['payload']}")
                handler = HANDLERS.get(job["kind"])
                try:
                    if handler is None:
                        raise ValueError(f"обработчик не умеет задачи «{job['kind']}»")
                    result = handler(job, ctx)
                    body = {"status": "done", "result": result, "message": describe(job["kind"], result)}
                except Exception as exc:  # noqa: BLE001 — сбой одной задачи не останавливает очередь
                    body = {"status": "failed", "message": f"{type(exc).__name__}: {exc}"[:2000]}
                log(f"задача №{job['id']}: {body['status']} {body.get('message', '')}")
                try:
                    platform.post(f"{job['id']}/result", body)
                except (RuntimeError, URLError, OSError) as exc:
                    log(f"итог не отправлен ({exc}); при перезапуске задача вернётся в очередь")
                current.clear()
            idle_since = time.time()
        elif queued:
            log("модель не поднялась — задачи ждут; повтор через минуту")
            time.sleep(60)
            continue
        if args.once:
            model.stop()
            beat()  # страница сразу видит, что модель выключена
            return 0
        if model.started_by_me and time.time() - idle_since > args.idle_min * 60:
            model.stop()
            beat()
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
