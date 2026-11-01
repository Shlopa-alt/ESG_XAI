"""Статья по DOI: метаданные и ссылка на открытый PDF из OpenAlex, скачивание PDF.

Ссылку на PDF даёт внешний сервис, поэтому скачивание идёт только по http(s) и только на
публичные адреса — и на каждом перенаправлении: сервер платформы стоит во внутренней сети.
"""

import ipaddress
import json
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

OPENALEX = "https://api.openalex.org/works/https://doi.org/"
UA = "ESG-Open-Research/0.1 (article import)"
DOI_RE = re.compile(r"10\.\d{4,9}/\S+")


class FetchError(Exception):
    """Понятная человеку причина, по которой статью не скачать."""


def normalize_doi(value: str) -> str:
    """«https://doi.org/10.3390/X», «doi:10.3390/X», « 10.3390/X. » → «10.3390/x» (как в KBRAG)."""
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    doi = doi.strip().rstrip(".,;)").lower()
    if not DOI_RE.fullmatch(doi):
        raise FetchError(f"Это не DOI: «{value.strip()}». Пример: 10.3390/electronics14030417")
    return doi


def doc_id_for_doi(doi: str) -> str:
    """Идентификатор статьи в KBRAG для DOI (kbrag/library/meta.py: slug)."""
    return re.sub(r"[^a-z0-9._-]+", "_", doi.strip().lower()).strip("_")


def _check_public(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError(f"Ссылка на PDF не http(s): {url}")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise FetchError(f"Адрес {parts.hostname} не найден") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FetchError(f"Ссылка ведёт во внутреннюю сеть ({parts.hostname}) — не скачиваю")


class _PublicOnly(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_PublicOnly)


def _get(url: str, timeout_s: float, limit: int) -> bytes:
    _check_public(url)
    try:
        with _opener.open(Request(url, headers={"User-Agent": UA}), timeout=timeout_s) as r:
            data: bytes = r.read(limit + 1)
    except HTTPError as exc:
        raise FetchError(f"{urlsplit(url).hostname} ответил {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{urlsplit(url).hostname} недоступен: {exc}") from exc
    if len(data) > limit:
        raise FetchError(f"Файл больше {limit // 2**20} МБ")
    return data


def openalex_work(doi: str, timeout_s: float = 30.0) -> dict[str, Any]:
    """Метаданные статьи и кандидаты на открытый PDF."""
    try:
        raw = _get(OPENALEX + quote(doi, safe="/"), timeout_s, 5 * 2**20)
    except FetchError as exc:
        if "ответил 404" in str(exc):
            raise FetchError(f"OpenAlex не знает DOI {doi}") from exc
        raise
    work = json.loads(raw)
    pdfs: list[str] = []
    for loc in [work.get("best_oa_location") or {}, *(work.get("locations") or [])]:
        url = (loc or {}).get("pdf_url")
        if url and url not in pdfs:
            pdfs.append(url)
    source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    return {
        "title": (work.get("title") or work.get("display_name") or "").strip(),
        "year": work.get("publication_year"),
        "authors": [a["author"]["display_name"] for a in work.get("authorships") or []
                    if (a.get("author") or {}).get("display_name")],
        "journal": source,
        "is_oa": bool((work.get("open_access") or {}).get("is_oa")),
        "pdf_urls": pdfs,
    }


def download_pdf(urls: list[str], limit: int, timeout_s: float = 90.0) -> tuple[bytes, str]:
    """Первый из кандидатов, который отдаёт настоящий PDF: (данные, адрес)."""
    reasons = []
    for url in urls:
        try:
            data = _get(url, timeout_s, limit)
        except FetchError as exc:
            reasons.append(str(exc))
            continue
        if data.startswith(b"%PDF-"):
            return data, url
        reasons.append(f"{urlsplit(url).hostname} отдал не PDF (часто — страница с капчей)")
    raise FetchError("Открытый PDF скачать не удалось: " + "; ".join(reasons) if reasons
                     else "У статьи нет открытого PDF — скачайте его сами и загрузите файлом")
