from .common import normalize, scrape_deadline_from_page
import requests, re, time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

PROVIDER = {"name":"FAPESP Chamadas","group":"América Latina / Brasil"}

def fetch(regex, cfg):
    # NÃO usamos /chamadas/ (bloqueia com 403 em alguns ISPs).
    # Varremos diretamente as categorias oficiais.
    CATEGORY_URLS = [
        # host sem www
        "https://fapesp.br/chamadas-proprias/",
        "https://fapesp.br/colaboracao-internacional/",
        "https://fapesp.br/colaboracao-nacional-regional/",
        "https://fapesp.br/programas-fapesp/",
        "https://fapesp.br/pesquisa-para-inovacao/",
        # por redundância, também com www (requests seguirá o 301 → sem www)
        "https://www.fapesp.br/chamadas-proprias/",
        "https://www.fapesp.br/colaboracao-internacional/",
        "https://www.fapesp.br/colaboracao-nacional-regional/",
        "https://www.fapesp.br/programas-fapesp/",
        "https://www.fapesp.br/pesquisa-para-inovacao/",
    ]

    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://fapesp.br/",
    })

    def get_soup(url: str) -> BeautifulSoup | None:
        try:
            r = s.get(url, timeout=40, allow_redirects=True)
        except Exception:
            return None
        # NÃO chamamos raise_for_status: se 403/404, apenas ignoramos a URL
        if not (200 <= r.status_code < 300) or not r.text.strip():
            return None
        return BeautifulSoup(r.text, "html.parser")

    def absolutize(href: str, page_url: str) -> str | None:
        if not href: return None
        h = href.strip()
        if h.startswith("#") or h.lower().startswith("javascript:"):
            return None
        if urlparse(h).scheme in ("http","https"):
            return h
        return urljoin(page_url, h)

    # Páginas oficiais de chamada seguem esse padrão:
    # https://fapesp.br/<numero>/<slug>
    CALL_URL_RE = re.compile(r"^https?://(?:www\.)?fapesp\.br/\d+/.+", re.I)

    out, seen = [], set()

    def collect_from(url: str, depth: int = 0):
        """Coleta links de chamadas em uma página de categoria (e paginações básicas)."""
        soup = get_soup(url)
        if not soup:
            return

        # 1) varre todos <a> e filtra só o que é página de chamada
        for a in soup.find_all("a", href=True):
            title = normalize(a.get_text())
            if not title:
                continue
            href = absolutize(a["href"], url)
            if not href or not CALL_URL_RE.match(href):
                continue
            if href in seen:
                continue
            if regex and not regex.search(title):
                continue
            seen.add(href)
            dl = scrape_deadline_from_page(href)
            out.append({
                "source": PROVIDER["name"],
                "title": title,
                "link": href,
                "deadline": dl,
                "published": None,
                "agency": "FAPESP",
                "region": "Brasil",
                "raw": {}
            })

        # 2) paginação simples (quando existir): “Próxima”, números etc.
        if depth >= 5:  # trava de segurança
            return
        pager_candidates = []
        for a in soup.find_all("a", href=True):
            t = normalize(a.get_text() or "")
            if t in ("próxima","proxima","seguinte") or re.fullmatch(r"\d+", t or ""):
                u = absolutize(a["href"], url)
                if u and u not in pager_candidates:
                    pager_candidates.append(u)
        for nxt in pager_candidates:
            collect_from(nxt, depth + 1)

    # Coleta em todas as categorias que responderem 200
    for u in CATEGORY_URLS:
        collect_from(u)
        time.sleep(0.2)  # pequeno respiro para não irritar o WAF

    return out
