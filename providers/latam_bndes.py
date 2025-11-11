from .common import normalize, scrape_deadline_from_page  # scrape_deadline_from_page não será usado, mas mantive o import
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote

PROVIDER = {"name":"BNDES Chamadas","group":"América Latina / Brasil"}

INDEX_URL = "https://www.bndes.gov.br/wps/portal/site/home/mercado-de-capitais/fundos-de-investimentos/chamadas-publicas-para-selecao-de-fundos"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123 Safari/537.36"
    )
}

def _abs(base: str, href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if urlparse(href).scheme in ("http", "https"):
        return href
    return urljoin(base, href)

def fetch(regex, cfg):
    r = requests.get(INDEX_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href_raw = a.get("href", "")
        if not href_raw:
            continue

        # Absolutiza e DECODIFICA para conseguir casar '.../chamadas-publicas-para-fundos...' mesmo quando vem como %2F
        href_abs = _abs(INDEX_URL, href_raw)
        href_dec = unquote(href_abs).lower()

        # Editais do BNDES nessa página têm SEMPRE '?1dmy' e apontam para '.../chamadas-publicas-para-fundos...'
        if "?1dmy" not in href_dec or "chamadas-publicas-para-fundos" not in href_dec:
            continue

        # Título “limpo”; não dependemos de startswith para não quebrar se houver bullet/ícone
        title = normalize(a.get_text(" ", strip=True) or "") or "Chamada Pública - BNDES"

        # Aplica o seu regex (no título + href decodificado). Se a regex estiver vazia, no seu main vira .+ (passa tudo).
        if not regex.search(f"{title} {href_dec}"):
            continue

        key = (title, href_abs)
        if key in seen:
            continue
        seen.add(key)

        # Como você pediu “só os links”, não vamos extrair deadline (evita cortes por MIN_DAYS).
        dl = None

        # ⚠️ Mantendo exatamente a mesma estrutura e os mesmos nomes de campos no append:
        out.append({
            "source": PROVIDER["name"],
            "title": title,
            "link": href_abs,
            "deadline": dl,
            "published": None,
            "agency": "BNDES",
            "region": "Brasil",
            "raw": {}
        })

    return out
