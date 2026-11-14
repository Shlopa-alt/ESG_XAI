"""Ссылки на данные в статьях банка: найти, развернуть страницу репозитория в файлы, скачать.

Только стандартная библиотека — как и весь обработчик (runner/qwen/worker.py). Задача `data_links`:
1. текст статьи — из разметки docling (все строки текста и адреса ссылок);
2. ссылки и DOI наборов данных с предложением вокруг — кандидаты, если это репозиторий данных,
   прямая ссылка на файл таблицы или рядом сказано «данные доступны…»; ссылки на статьи, журналы и
   лицензии отбрасываются;
3. страница Zenodo, figshare и GitHub — в ссылки на файлы (их API), прямая ссылка — как есть;
4. скачивание: только http(s), только публичные адреса (проверка на каждом перенаправлении — машина
   стоит во внутренней сети), не больше limit байт; из zip — первый CSV или XLSX.
Что это данные самих авторов, решает Qwen (в worker.py); разбирает таблицу и хранит файл платформа.
"""

import hashlib
import io
import ipaddress
import json
import re
import socket
import zipfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

UA = "ESG-Open-Research/0.1 (article data links)"
TABLE_EXT = (".csv", ".tsv", ".xlsx", ".xlsm")
DATA_EXT = (*TABLE_EXT, ".xls", ".zip", ".json", ".dta", ".sav", ".txt")
DATA_HOSTS = (
    "zenodo.org", "figshare.com", "data.mendeley.com", "dataverse.", "datadryad.org", "osf.io",
    "github.com", "raw.githubusercontent.com", "kaggle.com", "data.worldbank.org", "databank.worldbank.org",
    "data.oecd.org", "stats.oecd.org", "ec.europa.eu/eurostat", "rosstat.gov.ru", "fedstat.ru",
    "data.gov", "icpsr.umich.edu", "openicpsr.org", "data.europa.eu", "cbr.ru/statistics",
)
# DOI наборов данных: Zenodo, figshare, Mendeley Data, Dataverse, Dryad, OSF, ICPSR, PANGAEA
DATA_DOI = re.compile(
    r"10\.(?:5281/zenodo\.\d+|6084/m9\.figshare\.[\d.v]+|17632/[\w.]+|7910/dvn/[\w]+|5061/dryad\.[\w]+|"
    r"17605/osf\.io/\w+|3886/icpsr[\w.]+|1594/pangaea\.\d+)",
    re.IGNORECASE,
)
NOT_DATA_HOSTS = ("doi.org", "creativecommons.org", "orcid.org", "sciencedirect.com", "springer.com",
                  "wiley.com", "tandfonline.com", "mdpi.com", "elsevier.com", "scopus.com",
                  "webofscience.com", "researchgate.net", "scholar.google", "jstor.org", "ssrn.com",
                  "elibrary.ru", "cyberleninka.ru", "twitter.com", "x.com", "linkedin.com")
DATA_WORDS = re.compile(
    r"data (?:are|is) (?:publicly |freely |openly )?available|data availability|dataset|data set|"
    r"supplementary (?:data|material)|replication (?:files|package)|данные доступны|набор данных|"
    r"исходные данные|репозитори",
    re.IGNORECASE,
)
URL = re.compile(r"https?://[^\s<>\"'\]\)}]+", re.IGNORECASE)
MAX_LINKS = 10  # кандидатов на статью — дальше статья скорее перечисляет литературу


class FetchError(Exception):
    """Понятная человеку причина, по которой файл не скачать."""


def article_text(docling: Any) -> str:
    """Все строки текста и адреса ссылок из разметки docling."""
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and k in ("text", "orig", "hyperlink", "uri", "url"):
                    out.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(docling)
    return "\n".join(out)


def _sentence(text: str, start: int, end: int) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    rights = [r for r in (text.find(". ", end), text.find("\n", end)) if r != -1]
    right = min(rights) if rights else len(text)
    return " ".join(text[left + 1 if left >= 0 else 0: right + 1].split())[:500]


def _clean(url: str) -> str:
    return url.rstrip(".,;:")


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def candidate(url: str, context: str) -> str:
    """Почему ссылка похожа на данные ("" — не похожа)."""
    host, path = _host(url), urlsplit(url).path.lower()
    if DATA_DOI.search(url):
        return "DOI набора данных"
    if path.endswith(DATA_EXT):
        return f"ссылка на файл {path.rsplit('.', 1)[-1].upper()}"
    if any(h in url.lower() for h in DATA_HOSTS):
        return f"репозиторий данных ({host})"
    if any(host == h or host.endswith("." + h) for h in NOT_DATA_HOSTS):
        return ""
    if DATA_WORDS.search(context):
        return "рядом сказано, что здесь данные"
    return ""


def find_links(text: str) -> list[dict[str, str]]:
    """Ссылки на данные с предложением вокруг: [{url, context, reason}] без повторов."""
    seen: set[str] = set()
    out = []
    found = [(m.start(), m.end(), _clean(m.group(0))) for m in URL.finditer(text)]
    found += [(m.start(), m.end(), "https://doi.org/" + m.group(0)) for m in DATA_DOI.finditer(text)
              if "doi.org/" + m.group(0).lower() not in text.lower()]
    for start, end, url in sorted(found):
        key = url.lower().rstrip("/")
        if key in seen:
            continue
        context = _sentence(text, start, end)
        reason = candidate(url, context)
        if reason:
            seen.add(key)
            out.append({"url": url, "context": context, "reason": reason})
        if len(out) >= MAX_LINKS:
            break
    return out


# --- скачивание только с публичных адресов ---


def check_public(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError(f"не http(s): {url}")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise FetchError(f"адрес {parts.hostname} не найден") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise FetchError(f"ссылка ведёт во внутреннюю сеть ({parts.hostname}) — не скачиваю")


class _PublicOnly(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_PublicOnly)


def get(url: str, limit: int, timeout_s: float = 60) -> tuple[bytes, str, str]:
    """(данные, адрес после перенаправлений, тип содержимого). Больше limit — FetchError."""
    check_public(url)
    try:
        with _opener.open(Request(url, headers={"User-Agent": UA}), timeout=timeout_s) as r:
            data: bytes = r.read(limit + 1)
            final, ctype = r.geturl(), r.headers.get("Content-Type", "")
    except HTTPError as exc:
        raise FetchError(f"{_host(url)} ответил {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{_host(url)} недоступен: {exc}") from exc
    if len(data) > limit:
        raise FetchError(f"файл больше {limit // 2**20} МБ")
    return data, final, ctype


def github_raw(url: str) -> str:
    """github.com/u/r/blob/ветка/путь → raw.githubusercontent.com/u/r/ветка/путь; иначе ""."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else ""


def zenodo_id(url: str) -> str:
    m = re.search(r"zenodo\.org/(?:records?|deposit)/(\d+)", url) or re.search(r"zenodo\.(\d+)", url, re.I)
    return m.group(1) if m else ""


def figshare_id(url: str) -> str:
    m = re.search(r"figshare\.com/articles/(?:[^/]+/)*(\d+)", url) or re.search(r"figshare\.(\d+)", url, re.I)
    return m.group(1) if m else ""


def _api_files(url: str, limit: int) -> list[tuple[str, str]]:
    """Файлы записи Zenodo или figshare: [(имя, ссылка)]."""
    zid, fid = zenodo_id(url), figshare_id(url)
    if zid:
        data = json.loads(get(f"https://zenodo.org/api/records/{zid}", 5 * 2**20)[0])
        return [(f.get("key", ""), (f.get("links") or {}).get("self", "")) for f in data.get("files") or []]
    if fid:
        data = json.loads(get(f"https://api.figshare.com/v2/articles/{fid}", 5 * 2**20)[0])
        return [(f.get("name", ""), f.get("download_url", "")) for f in data.get("files") or []]
    return []


def resolve(url: str, limit: int) -> list[tuple[str, str]]:
    """Ссылка → файлы таблиц, которые можно скачать: [(имя, ссылка)]; пусто — автоматически нельзя."""
    raw = github_raw(url)
    if raw:
        url = raw
    path = urlsplit(url).path
    if path.lower().endswith(DATA_EXT):
        return [(path.rsplit("/", 1)[-1], url)]
    files = _api_files(url, limit)
    if not files and _host(url) == "doi.org":
        _, final, _ = get(url, 5 * 2**20)  # DOI → страница записи, её разворачиваем
        if final != url:
            return resolve(final, limit)
    return [(n, u) for n, u in files if u and n.lower().endswith((*TABLE_EXT, ".zip"))][:3]


def from_zip(data: bytes, limit: int) -> tuple[bytes, str]:
    """Первый CSV или XLSX из архива: (данные, имя в архиве)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FetchError("архив не открывается") from exc
    for info in z.infolist():
        if info.filename.lower().endswith(TABLE_EXT) and not info.filename.startswith("__MACOSX"):
            if info.file_size > limit:
                raise FetchError(f"{info.filename} в архиве больше {limit // 2**20} МБ")
            return z.read(info), info.filename
    raise FetchError("в архиве нет CSV или XLSX")


def fetch_table(url: str, limit: int) -> dict[str, Any]:
    """Скачать первый файл-таблицу по ссылке: {url, name, sha256, size, content_b64}.
    Нельзя — FetchError с причиной."""
    import base64

    files = resolve(url, limit)
    if not files:
        raise FetchError("по ссылке нет файла таблицы, который можно скачать автоматически "
                         "(страница, вход или капча) — скачайте вручную")
    reasons = []
    for name, link in files:
        try:
            data, final, _ = get(link, limit)
            if name.lower().endswith(".zip"):
                data, inner = from_zip(data, limit)
                name = f"{name}/{inner}"
            if name.lower().endswith(".xls"):
                raise FetchError("формат .xls (старый Excel) не разбирается — сохраните как .xlsx")
            return {"url": final, "name": name.rsplit("/", 1)[-1], "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data), "content_b64": base64.b64encode(data).decode()}
        except FetchError as exc:
            reasons.append(f"{name}: {exc}")
    raise FetchError("; ".join(reasons))
