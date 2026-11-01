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
        self.ctx = ssl.create_default_context(cafile=str(ca)) if ca.is_file() else None

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


def chat(prompt: str, max_tokens: int = 200, system: str = "", schema: dict[str, Any] | None = None) -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt + " /no_think"}]
    body: dict[str, Any] = {"model": "qwen3-14b", "max_tokens": max_tokens, "temperature": 0.3,
                            "messages": messages}
    if schema is not None:
        # vLLM выводит ровно по схеме: с «просто JSON» модель иногда отвечала пустым {}
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
    req = Request(f"{LLM_URL}/v1/chat/completions", data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=300) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def ask_json(prompt: str, max_tokens: int, system: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Ответ модели по JSON-схеме; не разобрался или без обязательных полей — ещё одна попытка."""
    required = schema.get("required", [])
    for _ in range(2):
        try:
            data = json.loads(chat(prompt, max_tokens, system, schema))
        except ValueError:
            continue
        if isinstance(data, dict) and all(k in data for k in required):
            return data
    raise ValueError("модель не дала ответ по схеме")


_S, _B, _I = {"type": "string"}, {"type": "boolean"}, {"type": "integer"}
PLAN_SCHEMA = {"type": "object", "required": ["queries", "entities"], "properties": {
    "queries": {"type": "array", "items": _S, "maxItems": 3}, "entities": {"type": "array", "items": _S, "maxItems": 5}}}
HYP_SCHEMA = {"type": "object", "required": ["hypotheses"], "properties": {"hypotheses": {
    "type": "array", "maxItems": 3, "items": {"type": "object", "required": [
        "title", "statement", "rationale", "fragments", "dataset", "method", "data_needed"], "properties": {
        "title": _S, "statement": _S, "rationale": _S, "fragments": {"type": "array", "items": _I},
        "dataset": _S, "method": _S, "data_needed": _S}}}}}
CHECK_SCHEMA = {"type": "object", "required": ["task_output", "grounded", "no_extra", "comment"], "properties": {
    "task_output": _B, "grounded": _B, "no_extra": _B, "comment": _S}}


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


HYP_SYSTEM = """Ты — исследователь лаборатории ИИ в ESG-управлении. Ты предлагаешь гипотезы для задания
методики лаборатории. Гипотеза — проверяемое утверждение о связи (что влияет на что, в какую сторону, на
каком горизонте, на каких данных), которое можно подтвердить или опровергнуть расчётом.

Правила:
1. Опирайся ТОЛЬКО на пронумерованные опоры ниже (фрагменты статей и факты графа). Каждая гипотеза ссылается на
   номера опор, из которых она следует (поле "fragments"). Без опоры гипотезу не предлагай.
2. Гипотеза должна служить заданию: те же входы и выходы, что в задании и его разделах.
3. Не повторяй гипотезы, которые уже есть.
4. "dataset" — код датасета из списка, только если в его описании есть нужные показатели; иначе "" и в
   "data_needed" — какие данные нужны и где их взять. Датасет и "data_needed" вместе не бывают.
5. "method" — ключ метода из списка, только если этот метод считается на выбранном датасете; иначе
   коротко словами: каким методом проверять.
6. Пиши по-русски; названия показателей и терминов из статей можно оставить как в статье.
7. Лучше 1 хорошо обоснованная гипотеза, чем 3 слабых. Нечего предложить — верни пустой список.

Ответ — только JSON: {"hypotheses": [{"title": "коротко, до 120 знаков", "statement": "проверяемое
утверждение", "rationale": "почему так думаем, со ссылками [n] на фрагменты", "fragments": [1, 3],
"dataset": "DS-04", "method": "exp007-hsu", "data_needed": ""}]}"""

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


def _evidence(target: dict[str, Any], token: str) -> list[dict[str, Any]]:
    """Опоры по заданию: фрагменты статей по коротким запросам и факты графа о ключевых сущностях
    (у каждого факта — дословная цитата из статьи). Материалы лаборатории (lab_*) — сама
    постановка, не опора."""
    queries, entities = _plan(target)
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for q in [target["title"], *queries]:
        try:
            found = kbrag_get("search", {"q": query_text(q, 120), "kb": "esg", "limit": 5}, token).get("hits", [])
        except (TimeoutError, URLError, OSError) as exc:
            log(f"  поиск «{q[:60]}» не ответил ({exc}) — пропускаю запрос")
            continue
        for h in found:
            if h["chunk_id"] in seen or h["doc_id"].startswith("lab_") or len(items) >= 8:
                continue
            seen.add(h["chunk_id"])
            items.append({"kind": "fragment", "doc_id": h["doc_id"], "title": h["title"], "year": h.get("year"),
                          "url": h.get("url"), "pages": h.get("pages") or [], "text": " ".join(h["text"].split())})
    for name in entities:
        try:
            ds = kbrag_get("dataset", {"name": name, "kb": "esg"}, token)
        except (TimeoutError, URLError, OSError, HTTPError):
            continue
        # сначала связи с направлением: «повышает», «снижает», «не влияет на»
        facts = sorted(ds.get("facts") or [], key=lambda f: (not re.search(r"повыша|снижа|не влияет", f["relation"]),
                                                              -f.get("documents", 0)))
        for f in facts[:3]:
            q = (f.get("quotes") or [{}])[0]
            if not q.get("doc_id") or q["doc_id"].startswith("lab_"):
                continue
            a, b = (f["other"], f["about"]) if f.get("direction") == "←" else (f["about"], f["other"])
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


CHECK_SYSTEM = """Ты — строгий рецензент лаборатории. Тебе дают задание методики, гипотезу и опоры (цитаты
из статей), на которые она ссылается. Ответь на три вопроса:
1. "task_output": о том ли результате гипотеза, что требует задание? Например, задание о бюджете региона,
   а гипотеза о прибыли компании — false; задание о компаниях, гипотеза о компаниях — true.
2. "grounded": прямо ли опоры говорят о тех же показателях и той же связи (направление не противоречит)?
3. "no_extra": нет ли в утверждении того, чего в опорах нет (другой горизонт, «но в долгосрочной
   перспективе…», новые показатели, механизмы)?
Сомневаешься — false. Ответ — только JSON:
{"task_output": true/false, "grounded": true/false, "no_extra": true/false, "comment": "одной фразой"}"""


def _verify(h: dict[str, Any], cited: list[dict[str, Any]], target: dict[str, Any]) -> tuple[bool, str]:
    """Вторая пара глаз: гипотеза отвечает заданию и следует из процитированных опор (видна только им)."""
    quotes = "\n".join(f"- {it.get('fact', '')} «{it['text'][:500]}» («{it['title']}»)" for it in cited)
    prompt = (f"ЗАДАНИЕ: {target['title']}\n{target['content'][:1200]}\n\n"
              f"ГИПОТЕЗА: {h['statement']}\nОБОСНОВАНИЕ: {h['rationale']}\n\nОПОРЫ:\n{quotes}")
    try:
        data = ask_json(prompt, 250, CHECK_SYSTEM, CHECK_SCHEMA)
    except (ValueError, TimeoutError, URLError, OSError):
        return False, "проверка опор не ответила"
    failed = [name for key, name in (("task_output", "не о результате задания"), ("grounded", "опоры не о том"),
                                     ("no_extra", "сверх опор")) if data.get(key) is not True]
    comment = str(data.get("comment") or "")[:300]
    return not failed, (f"{'; '.join(failed)} — {comment}" if failed else comment)


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
    for target in context["targets"]:
        if target["pending_qwen"] >= context["limits"]["pending"]:
            skipped.append(f"{target['number']}: ждут рецензии {target['pending_qwen']}")
            continue
        # гипотезы этого прохода по другим заданиям — тоже «уже есть»: без повторов между заданиями
        target = {**target, "existing": target["existing"] + [
            {"code": f"новая ({x['node']})", "title": x["title"], "status": "предложена сейчас"} for x in out]}
        items = _evidence(target, ctx["kbrag_token"])
        if not items:
            skipped.append(f"{target['number']}: в базе нет опор")
            continue
        answer = json.dumps(ask_json(_prompt(target, context, items), 1800, HYP_SYSTEM, HYP_SCHEMA), ensure_ascii=False)
        answers[target["number"]] = answer[:4000]
        before = len(out)
        for item in _parse(answer)[: context["limits"]["per_run"]]:
            nums = _numbers(item.get("fragments"), len(items))
            if not nums:
                continue  # без опоры из найденного — не гипотеза
            h = {k: str(item.get(k) or "") for k in ("title", "statement", "rationale", "dataset", "method",
                                                     "data_needed")}
            ok, comment = _verify(h, [items[n - 1] for n in nums], target)
            if not ok:
                rejected.append({"node": target["number"], "title": h["title"], "why": comment})
                continue
            h["rationale"] = f"{h['rationale']}\nПроверка опор (Qwen): {comment}".strip()
            out.append({**h, "node": target["number"], "refs": [_ref(items[n - 1]) for n in nums]})
        facts = sum(1 for it in items if it["kind"] == "fact")
        log(f"  {target['number']}: опор {len(items)} (фактов {facts}), гипотез {len(out) - before}")
        if len(out) == before:
            skipped.append(f"{target['number']}: модель не нашла обоснованной гипотезы")
    # ответы модели — в журнал задачи: по ним видно, почему по заданию ничего не предложено
    (ctx["logs"] / f"qwen-hypotheses-{job['id']}.json").write_text(
        json.dumps(answers, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"hypotheses": out, "skipped": skipped, "rejected": rejected, "targets": len(context["targets"])}


EXP_SYSTEM = """Ты — исследователь лаборатории ИИ в ESG-управлении. Гипотезу приняли к проверке; предложи
эксперимент, который её подтвердит или опровергнет.

Правила:
1. "method" — ключ метода ТОЛЬКО из библиотеки. Повтор (scope replication) — только на своём датасете.
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
        f"{s['description'][:300]} Числовые столбцы: "
        + (", ".join(s["numeric_columns"]) if s["table"] else "файл не таблица CSV — общие методы его не читают")
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


HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "ping": job_ping,
    "graph": job_graph,
    "hypotheses": job_hypotheses,
    "experiment": job_experiment,
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
    if kind == "hypotheses":
        return f"Qwen предложила {len(result.get('hypotheses') or [])} (платформа проверит опоры)"
    return ""


def main() -> int:
    env = read_env(DEPLOY / ".env")
    ap = argparse.ArgumentParser(description="Обработчик очереди задач Qwen")
    ap.add_argument("--platform", default=f"https://127.0.0.1:{env.get('HTTP_PORT', '8080')}")
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
