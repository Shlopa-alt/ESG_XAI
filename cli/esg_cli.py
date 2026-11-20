"""esg — командная строка платформы ESG Open Research (п. 10 фидбека: работа без сайта, «провал в ручной режим»).

Только стандартная библиотека Python 3.11+. Вход — тем же логином и паролем, что на сайте; пароль
вводится в терминале и нигде не хранится, хранится только cookie сессии (~/.esg/cookies.txt).
Или личным токеном открытого API (сайт → «Доступ к API»): переменная ESG_TOKEN либо
esg login --token — токен хранится в ~/.esg/token, доступном только вам.

    esg login --url https://<адрес платформы>       войти
    esg login --token --url https://<адрес>         войти токеном API (для скриптов и серверов)
    esg datasets                                     наборы данных
    esg dataset DS-09                                версии набора (номер версии — для download)
    esg download 12 -o data/                         файл версии данных (sha256 сверяется)
    esg notebook --run 57 -o work/                   архив «взять в свои руки» с ноутбуком Jupyter
    esg notebook --snapshot 12 -o work/              то же для версии данных
    esg runs --experiment EXP-010                    расчёты
    esg run 57                                       расчёт: статус, параметры, итоги
    esg templates                                    методы библиотеки и их параметры
    esg estimate correlation-scan --snapshot 12 --param method=partial
    esg launch correlation-scan --snapshot 12 --experiment EXP-010 --param method=partial
    esg upload-run EXP-010 results/…/run.json        свой расчёт — в реестр (нужен коммит репозитория)

Параметры: --param имя=значение; значение — JSON, если читается («["a","b"]», 50, true), иначе строка.
"""

import argparse
import getpass
import hashlib
import io
import json
import os
import sys
import zipfile
from http.cookiejar import LWPCookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener

HOME = Path(os.environ.get("ESG_HOME") or Path.home() / ".esg")
VERSION = "0.1"


class CliError(Exception):
    pass


class Api:
    """Платформа: JSON и файлы по сессии (cookie), как у сайта, или по токену API."""

    def __init__(self, home: Path = HOME) -> None:
        self.home = home
        self.config_path = home / "config.json"
        cfg = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.is_file() else {}
        self.url = str(os.environ.get("ESG_URL") or cfg.get("url") or "").rstrip("/")
        self.jar = LWPCookieJar(str(home / "cookies.txt"))
        if (home / "cookies.txt").is_file():
            self.jar.load(ignore_discard=True)
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        self.token_path = home / "token"
        saved = self.token_path.read_text(encoding="utf-8").strip() if self.token_path.is_file() else ""
        self.token = str(os.environ.get("ESG_TOKEN") or saved).strip()

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "User-Agent": f"esg-cli/{VERSION}"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def save_token(self, token: str) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        # файл сразу только для владельца — токен не бывает доступен другим даже на миг
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
        self.token = token

    def save(self, url: str | None = None) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        if url is not None:
            self.url = url.rstrip("/")
            self.config_path.write_text(json.dumps({"url": self.url}), encoding="utf-8")
        self.jar.save(ignore_discard=True)
        try:
            os.chmod(self.home / "cookies.txt", 0o600)
        except OSError:
            pass

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, bytes, dict[str, str]]:
        if not self.url:
            raise CliError("Адрес платформы не задан: esg login --url https://…")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(self.url + path, data=data, method=method, headers=self.headers())
        try:
            with self.opener.open(req, timeout=300) as r:
                return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
        except HTTPError as exc:
            return exc.code, exc.read(), {k.lower(): v for k, v in exc.headers.items()}
        except URLError as exc:
            raise CliError(f"Платформа недоступна: {exc.reason}") from exc

    def need_login(self) -> str:
        if self.token:
            return "Токен API не принят (отозван или истёк): новый — на сайте, «Доступ к API»"
        return "Нужно войти: esg login"

    def json(self, method: str, path: str, body: Any = None) -> Any:
        code, raw, _ = self.request(method, path, body)
        out = json.loads(raw) if raw else None
        if code == 401:
            raise CliError(self.need_login())
        if code >= 400:
            detail = out.get("detail") if isinstance(out, dict) else None
            raise CliError(f"Платформа ответила {code}: {detail if isinstance(detail, str) else raw[:300]!r}")
        return out

    def file(self, path: str) -> tuple[bytes, dict[str, str]]:
        code, raw, headers = self.request("GET", path)
        if code == 401:
            raise CliError(self.need_login())
        if code >= 400:
            try:
                detail = json.loads(raw).get("detail")
            except ValueError:
                detail = raw[:300]
            raise CliError(f"Платформа ответила {code}: {detail}")
        return raw, headers


def parse_params(items: list[str], json_file: str | None) -> dict[str, Any]:
    params: dict[str, Any] = json.loads(Path(json_file).read_text(encoding="utf-8")) if json_file else {}
    for item in items:
        if "=" not in item:
            raise CliError(f"Параметр «{item}»: нужно имя=значение")
        k, v = item.split("=", 1)
        try:
            params[k.strip()] = json.loads(v)
        except ValueError:
            params[k.strip()] = v
    return params


def _filename(headers: dict[str, str], fallback: str) -> str:
    cd = headers.get("content-disposition", "")
    if "filename=" in cd:
        return Path(cd.split("filename=", 1)[1].strip('"; ')).name or fallback
    return fallback


def _table(rows: list[list[Any]], head: list[str]) -> str:
    cells = [head, *[[("" if c is None else str(c)) for c in r] for r in rows]]
    widths = [max(len(r[i]) for r in cells) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in cells)


# --- команды ---


def cmd_login(api: Api, a: argparse.Namespace) -> str:
    url = a.url or api.url
    if not url:
        raise CliError("Укажите адрес платформы: esg login --url https://…")
    api.url = url.rstrip("/")
    if a.token:
        api.token = getpass.getpass("Токен API (esg_…): ").strip()
        user = api.json("GET", "/api/auth/me")
        api.save_token(api.token)
        api.save(url)
        return f"Токен принят: {user.get('login')} ({user.get('role')}) на {api.url}"
    login = a.login or input("Логин: ").strip()
    password = getpass.getpass("Пароль: ")
    user = api.json("POST", "/api/auth/login", {"login": login, "password": password})
    api.save(url)
    return f"Вошли как {user.get('login')} ({user.get('role')}) на {api.url}"


def cmd_logout(api: Api, a: argparse.Namespace) -> str:
    if api.token_path.is_file():
        api.token_path.unlink()  # токен на сайте не отзывается — только забывается здесь
        api.token = ""
        return "Токен забыт на этом компьютере (отозвать его — на сайте, «Доступ к API»)"
    api.request("POST", "/api/auth/logout")
    api.jar.clear()
    api.save()
    return "Вышли"


def cmd_whoami(api: Api, a: argparse.Namespace) -> str:
    u = api.json("GET", "/api/auth/me")
    how = " — токен API" if api.token else ""
    return f"{u.get('login')} ({u.get('role')}) на {api.url}{how}"


def cmd_datasets(api: Api, a: argparse.Namespace) -> str:
    ds = api.json("GET", "/api/datasets")
    return _table([[d["code"], d.get("snapshots", ""), d["access_level"], d["title"]] for d in ds],
                  ["код", "версий", "доступ", "название"])


def cmd_dataset(api: Api, a: argparse.Namespace) -> str:
    d = api.json("GET", f"/api/datasets/{quote(a.code)}")
    rows = [[s.get("id"), s.get("version"), s.get("row_count"), str(s.get("sha256", ""))[:12]] for s in d.get("snapshots", [])]
    files = "" if d.get("can_see_files") else "\nФайлы под NDA — вам недоступны (правило 6)."
    return f"{d['code']} · {d['title']}\n" + _table(rows, ["номер", "версия", "строк", "sha256"]) + files


def cmd_download(api: Api, a: argparse.Namespace) -> str:
    raw, headers = api.file(f"/api/snapshots/{a.snapshot}/file")
    want = headers.get("x-sha256", "")
    got = hashlib.sha256(raw).hexdigest()
    if want and want != got:
        raise CliError(f"sha256 не совпал: записано {want[:12]}…, скачано {got[:12]}… — файл не сохранён")
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    path = out / _filename(headers, f"snapshot-{a.snapshot}.csv")
    path.write_bytes(raw)
    return f"{path} ({len(raw)} байт, sha256 {got[:12]}… совпадает)"


def cmd_notebook(api: Api, a: argparse.Namespace) -> str:
    path = f"/api/runs/{a.run}/manual.zip" if a.run else f"/api/snapshots/{a.snapshot}/manual.zip"
    raw, headers = api.file(path)
    name = _filename(headers, "esg-manual.zip")
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    if a.no_unzip:
        (out / name).write_bytes(raw)
        return f"{out / name}"
    dest = out / name.removesuffix(".zip")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for member in z.namelist():  # без выхода за папку архива
            target = (dest / member).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                raise CliError(f"Подозрительный путь в архиве: {member}")
        z.extractall(dest)
    nb = next((p.name for p in dest.glob("*.ipynb")), "")
    return f"{dest}\nОткройте: cd \"{dest}\" && jupyter notebook {nb}\nКак поставить окружение — README.txt"


def cmd_runs(api: Api, a: argparse.Namespace) -> str:
    runs = api.json("GET", f"/api/experiments/{quote(a.experiment)}/runs" if a.experiment else "/api/runs")
    runs = runs[: a.limit]
    return _table([[r["id"], r["experiment"], r["status"], r["template"], r["dataset"], r.get("author", "")] for r in runs],
                  ["№", "проверка", "статус", "метод", "данные", "кто"])


def cmd_run(api: Api, a: argparse.Namespace) -> str:
    r = api.json("GET", f"/api/runs/{a.id}")
    if a.json:
        return json.dumps(r, ensure_ascii=False, indent=2)
    params = (r.get("config") or {}).get("params") or {}
    lines = [f"Расчёт № {r['id']} · {r['experiment']} · {r['template']} · {r['status']}",
             f"Данные: {r['dataset']} (версия № {r.get('snapshot_id')}), коммит {str(r.get('runner_commit'))[:12] or '—'}",
             "Параметры: " + json.dumps(params, ensure_ascii=False)]
    if r.get("message"):
        lines.append(f"Сообщение: {r['message']}")
    summary = {k: v for k, v in (r.get("summary") or {}).items() if isinstance(v, int | float | str | bool)}
    if summary:
        lines.append("Итоги: " + json.dumps(summary, ensure_ascii=False))
    return "\n".join(lines)


def cmd_templates(api: Api, a: argparse.Namespace) -> str:
    out = []
    for t in api.json("GET", "/api/run-templates"):
        params = ", ".join(f"{p['name']}={json.dumps(p['default'], ensure_ascii=False)}" for p in t.get("params", []))
        out.append(f"{t['key']} — {t['title']}\n    {params}")
    return "\n".join(out)


def cmd_estimate(api: Api, a: argparse.Namespace) -> str:
    e = api.json("POST", "/api/runs/estimate", {"template": a.template, "snapshot_id": a.snapshot,
                                               "params": parse_params(a.param, a.params_json)})
    lines = [f"≈ {e.get('minutes')} мин ({e.get('low')}–{e.get('high')}), {e.get('resource')}; лимит метода {e.get('limit_min')} мин"]
    if e.get("blocked"):
        lines.append(f"Сейчас не запустить: {e['blocked']}")
    if not e.get("within_limit") and e.get("suggestion"):
        lines.append(f"Чтобы уложиться: {e['suggestion'].get('text')}")
    return "\n".join(lines)


def cmd_launch(api: Api, a: argparse.Namespace) -> str:
    r = api.json("POST", "/api/runs", {"template": a.template, "snapshot_id": a.snapshot, "experiment": a.experiment,
                                      "params": parse_params(a.param, a.params_json)})
    return f"Расчёт № {r['id']} в очереди ({r['experiment']}). Ход: esg run {r['id']}"


def cmd_upload_run(api: Api, a: argparse.Namespace) -> str:
    body = json.loads(Path(a.run_json).read_text(encoding="utf-8"))
    if len(str(body.get("runner_commit") or "")) < 7:
        raise CliError("В run.json нет коммита репозитория: расчёт шёл вне клона репозитория, в реестр такой не "
                       "берётся (правило 3). Повторите его в клоне репозитория на нужном коммите")
    r = api.json("POST", f"/api/experiments/{quote(a.experiment)}/runs", body)
    return f"Расчёт № {r['id']} записан в реестр {r['experiment']}: {r['status']}" + (f" — {r['note']}" if r.get("note") else "")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="esg", description="Командная строка ESG Open Research")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("login", help="войти")
    p.add_argument("--url")
    p.add_argument("--login")
    p.add_argument("--token", action="store_true", help="войти личным токеном API вместо пароля")
    p.set_defaults(fn=cmd_login)
    sub.add_parser("logout", help="выйти").set_defaults(fn=cmd_logout)
    sub.add_parser("whoami", help="кто вошёл").set_defaults(fn=cmd_whoami)
    sub.add_parser("datasets", help="наборы данных").set_defaults(fn=cmd_datasets)
    p = sub.add_parser("dataset", help="версии набора данных")
    p.add_argument("code")
    p.set_defaults(fn=cmd_dataset)
    p = sub.add_parser("download", help="файл версии данных")
    p.add_argument("snapshot", type=int)
    p.add_argument("-o", "--output", default=".")
    p.set_defaults(fn=cmd_download)
    p = sub.add_parser("notebook", help="архив с ноутбуком Jupyter: взять работу в свои руки")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", type=int)
    g.add_argument("--snapshot", type=int)
    p.add_argument("-o", "--output", default=".")
    p.add_argument("--no-unzip", action="store_true")
    p.set_defaults(fn=cmd_notebook)
    p = sub.add_parser("runs", help="расчёты")
    p.add_argument("--experiment")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_runs)
    p = sub.add_parser("run", help="расчёт")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_run)
    sub.add_parser("templates", help="методы библиотеки").set_defaults(fn=cmd_templates)
    for name, fn, help_ in (("estimate", cmd_estimate, "сколько займёт расчёт"), ("launch", cmd_launch, "запустить расчёт")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("template")
        p.add_argument("--snapshot", type=int, required=True)
        if name == "launch":
            p.add_argument("--experiment", required=True)
        p.add_argument("--param", action="append", default=[], metavar="имя=значение")
        p.add_argument("--params-json")
        p.set_defaults(fn=fn)
    p = sub.add_parser("upload-run", help="свой run.json — в реестр проверки")
    p.add_argument("experiment")
    p.add_argument("run_json")
    p.set_defaults(fn=cmd_upload_run)
    return ap


def main(argv: list[str] | None = None, api: Api | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        print(a.fn(api or Api(), a))
        return 0
    except CliError as exc:
        print(f"esg: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
