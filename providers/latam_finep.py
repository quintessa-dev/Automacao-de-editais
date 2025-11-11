# providers/latam_finep.py

# ============================================================
# IMPORTS (com fallback para rodar como script direto)
# ============================================================
try:
    # caminho normal quando é usado pelo main.py (pacote providers)
    from .common import normalize, scrape_deadline_from_page
except ImportError:
    # fallback quando você roda o arquivo direto: python providers/latam_finep.py
    import os, sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from providers.common import normalize, scrape_deadline_from_page  # type: ignore

import requests
import re
from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

PROVIDER = {"name": "FINEP Chamadas", "group": "América Latina / Brasil"}

# Usado no painel de diagnóstico
URL_HINT = "https://www.finep.gov.br/chamadas-publicas/chamadaspublicas?situacao=aberta"

# Flag global de debug (pode pôr True para testar rápido e depois voltar para False)
DEBUG_DEFAULT = False


# ============================================================
# HELPERS
# ============================================================
def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    })
    return s


def _absolutize(href: Optional[str], base: str) -> Optional[str]:
    if not href:
        return None
    h = href.strip()
    if not h or h.startswith("#") or h.lower().startswith("javascript:"):
        return None
    if urlparse(h).scheme in ("http", "https"):
        return h
    return urljoin(base, h)


def _is_call_url(u: str) -> bool:
    """
    Heurística simples para identificar páginas de chamada da FINEP.
    Ex.: https://www.finep.gov.br/chamadas-publicas/chamadapublica/1234
    """
    if "finep.gov.br" not in u:
        return False
    if "/chamadas-publicas/" not in u:
        return False
    # exclui a página de listagem
    if "chamadaspublicas" in u:
        return False
    return True


# Fallback para varrer o HTML cru por URLs de chamada
DETAIL_RE = re.compile(
    r"/chamadas-publicas/[a-zA-Z0-9\-_\/\?=&]+",
    re.I,
)


def _extract_title_from_listing(a: BeautifulSoup) -> str:
    """Tenta extrair um título razoável diretamente da listagem."""
    t = normalize(a.get_text())
    if t and len(t) > 3:
        return t

    t = normalize(a.get("title") or "")
    if t and len(t) > 3:
        return t

    for tag in ("h3", "h2", "strong"):
        p = a.find_parent()
        if not p:
            break
        hdr = p.find(tag)
        if hdr:
            tt = normalize(hdr.get_text())
            if tt and len(tt) > 3:
                return tt
    return ""


def _scrape_title_from_detail(sess: requests.Session, url: str, debug: bool = False) -> str:
    """Abre a página da chamada e tenta pegar o título (H1/H2 ou <title>)."""
    try:
        r = sess.get(url, timeout=60, allow_redirects=True)
    except Exception as e:
        if debug:
            print("[FINEP] erro ao abrir detalhe:", url, "->", e)
        return ""
    if not (200 <= r.status_code < 300) or not r.text.strip():
        if debug:
            print("[FINEP] detalhe vazio ou status != 2xx:", url, "->", r.status_code)
        return ""

    soup = BeautifulSoup(r.text, "html.parser")
    h = soup.find("h1") or soup.find("h2")
    if h:
        t = normalize(h.get_text())
        if t and len(t) > 3:
            return t
    if soup.title and soup.title.string:
        t = normalize(soup.title.string)
        if t and len(t) > 3:
            return t
    return ""


# ============================================================
# FUNÇÃO PRINCIPAL USADA PELO main.py
# ============================================================
def fetch(regex, cfg, _debug: bool = False):
    """
    Interface usada pelo main.py:
        items = fetch(regex_compilada, cfg_dict)

    Retorna lista de dicts com:
        {source,title,link,deadline,published,agency,region,raw}
    """
    START = "https://www.finep.gov.br/chamadas-publicas/chamadaspublicas?situacao=aberta"

    # decide se roda em modo verboso
    debug_cfg = str(cfg.get("FINEP_DEBUG", "0")).strip().lower() in ("1", "true", "yes", "sim")
    debug = bool(_debug or DEBUG_DEFAULT or debug_cfg)

    def log(*args):
        if debug:
            print("[FINEP]", *args)

    sess = _make_session()
    out, seen = [], set()

    def _add_item(href: str, title: str):
        """Aplica regex de filtro e monta o dict final."""
        if not title:
            return
        if regex and not regex.search(title):
            log("descartado por regex:", title)
            return
        if href in seen:
            return
        seen.add(href)
        dl = scrape_deadline_from_page(href)
        log("OK:", title, "->", href, "| deadline:", dl)
        out.append({
            "source": PROVIDER["name"],
            "title": title,
            "link": href,
            "deadline": dl,
            "published": None,
            "agency": "FINEP",
            "region": "Brasil",
            "raw": {},
        })

    def collect_from(list_url: str, depth: int = 0):
        log("coletando página de listagem:", list_url, "depth=", depth)
        try:
            r = sess.get(list_url, timeout=60, allow_redirects=True)
        except Exception as e:
            log("erro ao abrir listagem:", e)
            return
        if not (200 <= r.status_code < 300) or not r.text.strip():
            log("listagem vazia ou status != 2xx:", r.status_code)
            return

        soup = BeautifulSoup(r.text, "html.parser")

        # 1) Caminho principal: links <a> normais
        found_anchor = False
        for a in soup.find_all("a", href=True):
            href = _absolutize(a["href"], list_url)
            if not href:
                continue
            if not _is_call_url(href):
                continue
            found_anchor = True
            title = _extract_title_from_listing(a)
            if not title:
                # tenta pegar título do próprio detalhe
                title = _scrape_title_from_detail(sess, href, debug=debug)
            _add_item(href, title)

        # 2) Fallback: varre HTML cru por /chamadas-publicas/...
        if not found_anchor:
            log("nenhum <a> direto encontrado, usando fallback DETAIL_RE")
            for m in DETAIL_RE.finditer(r.text):
                raw_href = m.group(0)
                href = _absolutize(raw_href, list_url)
                if not href or href in seen or not _is_call_url(href):
                    continue
                title = _scrape_title_from_detail(sess, href, debug=debug)
                _add_item(href, title)

        # 3) Paginação: ?start=, "Próxima", "Seguinte", "Next"
        if depth >= 5:
            return
        next_links = []
        for a in soup.find_all("a", href=True):
            nhref = _absolutize(a["href"], list_url)
            if not nhref:
                continue
            txt = normalize(a.get_text() or "")
            if "start=" in nhref or txt in ("proxima", "próxima", "seguinte", "next"):
                if nhref not in next_links:
                    next_links.append(nhref)
        for nxt in next_links[:2]:
            collect_from(nxt, depth + 1)

    # executa a partir da página principal
    collect_from(START)
    log("TOTAL de itens coletados:", len(out))
    return out


# ============================================================
# TESTE RÁPIDO STANDALONE
# ============================================================
if __name__ == "__main__":
    """
    Teste rápido de retrievement SEM passar pelo Streamlit.

    Exemplos de uso (a partir da pasta 'python'):

        python providers/latam_finep.py
    ou:
        python -m providers.latam_finep
    """
    import json

    test_re = re.compile(r".*", re.I)  # regex "tudo" pra não filtrar por título
    data = fetch(test_re, cfg={}, _debug=True)

    print("\n=== RESUMO ===")
    print("Itens encontrados:", len(data))
    for it in data:
        print("-", it["title"], "->", it["link"], "| deadline:", it["deadline"])

    if data:
        print("\nPrimeiro item (JSON):")
        # datetime não era serializável, então eu converti tudo para string
        print(json.dumps(data[0], ensure_ascii=False, indent=2, default=str))
