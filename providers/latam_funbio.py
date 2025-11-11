# -*- coding: utf-8 -*-
from __future__ import annotations

from .common import normalize, scrape_deadline_from_page
import re, json, requests
from urllib.parse import urlparse

PROVIDER = {"name": "FUNBIO – Portal de Chamadas", "group": "América Latina / Brasil"}
URL_HINT = "https://preprod-chamadas.funbio.org.br/"
BASE_HOSTS = {"preprod-chamadas.funbio.org.br", "chamadas.funbio.org.br"}

# páginas institucionais que não são chamada
_SKIP_SLUGS = {
    "home","lista-de-selecoes","calendario-chamadas","receba-informacoes",
    "quem-somos","noticias","login","politica-de-privacidade","static"
}
# slugs problemáticos/antigos que dão 500
_BAD_SLUGS = {"gef-terrestre","fv-edital-xingu-2"}

_SLUG_RX = re.compile(r"^[a-z0-9-]+$", re.I)
_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36")
}

def _canon(url_or_path: str) -> str | None:
    """
    Converte qualquer uma das formas abaixo para https://host/<slug>:
      - /<slug>
      - /?slug=<slug>
      - /slug=<slug>
      - https://host/<slug>
      - https://host/?slug=<slug>
      - https://host/slug=<slug>
    Valida domínio + slug único; remove institucionais e slugs ruins.
    """
    if not url_or_path:
        return None
    s = url_or_path.strip().strip("'\"")
    if not s or s.startswith("#") or s.lower().startswith("javascript:"):
        return None

    # Absoluto?
    pu = urlparse(s)
    if pu.scheme in ("http", "https"):
        host = pu.netloc.lower()
        if host not in BASE_HOSTS:
            return None
        path = (pu.path or "/").strip("/")
        q = pu.query or ""
    else:
        # relativo a /
        host = "preprod-chamadas.funbio.org.br"
        if s.startswith("/"):
            path = s.strip("/"); q = ""
        else:
            # casos tipo "?slug=...": trate como relativo
            path = ""; q = s.lstrip("?")

    slug = None
    # /slug=meu-slug
    m = re.fullmatch(r"slug=([a-z0-9-]+)", path, flags=re.I)
    if m:
        slug = m.group(1)
    # /meu-slug
    if slug is None and path and "/" not in path:
        slug = path
    # ?slug=meu-slug
    if slug is None and q:
        mq = re.search(r"(?:^|[?&])slug=([a-z0-9-]+)(?:&|$)", q, flags=re.I)
        if mq:
            slug = mq.group(1)

    if not slug:
        return None
    slug = slug.lower()
    if slug in _SKIP_SLUGS or slug in _BAD_SLUGS or not _SLUG_RX.match(slug):
        return None
    return f"https://{host}/{slug}"

def _extract_slugs_from_html(html: str) -> set[str]:
    found: set[str] = set()

    # 1) URLs absolutas
    for m in re.finditer(r"https?://(?:preprod-)?chamadas\.funbio\.org\.br/[a-z0-9\-]+/?", html, flags=re.I):
        u = _canon(m.group(0))
        if u: found.add(u)

    # 2) href='/<slug>' ou href="/slug=<slug>"
    for m in re.finditer(r"href\s*=\s*['\"](/[^'\" >]+)['\"]", html, flags=re.I):
        u = _canon(m.group(1))
        if u: found.add(u)

    # 3) /slug=<slug> perdido no HTML
    for m in re.finditer(r"/slug=([a-z0-9\-]+)", html, flags=re.I):
        u = _canon(f"/slug={m.group(1)}")
        if u: found.add(u)

    return found

def _extract_slugs_from_next(html: str) -> set[str]:
    # Pega JSON do Next.js sem depender de BeautifulSoup
    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, flags=re.I|re.S)
    if not m:
        return set()
    try:
        data = json.loads(m.group(1))
        txt = json.dumps(data)
    except Exception:
        return set()

    found: set[str] = set()
    # "slug":"..."
    for mm in re.finditer(r'"slug"\s*:\s*"([a-z0-9\-]+)"', txt, flags=re.I):
        u = _canon(mm.group(1))
        if u: found.add(u)
    # URLs absolutas no JSON
    for mm in re.finditer(r"https?://(?:preprod-)?chamadas\.funbio\.org\.br/([a-z0-9\-]+)/?", txt, flags=re.I):
        u = _canon(mm.group(0))
        if u: found.add(u)
    return found

def _get_html(url: str) -> str:
    r = requests.get(url, headers=_UA, timeout=60)
    r.raise_for_status()
    return r.text

def fetch(regex, cfg):
    pages = [
        "https://preprod-chamadas.funbio.org.br/",
        "https://preprod-chamadas.funbio.org.br/lista-de-selecoes",
    ]

    urls: set[str] = set()
    for u in pages:
        try:
            html = _get_html(u)
        except Exception:
            continue
        urls |= _extract_slugs_from_html(html)
        urls |= _extract_slugs_from_next(html)

    # Nada de HEAD/GET de validação (preprod às vezes derruba)
    # Também não filtramos por regex — devolvemos os links pedidas.

    out = []
    for href in sorted(urls):
        slug = href.rstrip("/").split("/")[-1]
        title = normalize(slug.replace("-", " ")) or "Seleção FUNBIO"
        try:
            dl = scrape_deadline_from_page(href)
        except Exception:
            dl = None

        # ⚠️ manter exatamente a estrutura e os nomes dos campos:
        out.append({
            "source": PROVIDER["name"],
            "title": title[:180],
            "link": href,
            "deadline": dl,
            "published": None,
            "agency": "FUNBIO",
            "region": "Brasil",
            "raw": {}
        })

    return out
