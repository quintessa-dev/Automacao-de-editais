# providers/latam_caixa_fsa.py

# ============================================================
# IMPORTS (com fallback para rodar como script direto)
# ============================================================
try:
    # caminho normal quando é usado pelo main.py (pacote providers)
    from .common import normalize, scrape_deadline_from_page
except ImportError:
    # fallback quando você roda o arquivo direto: python providers/latam_caixa_fsa.py
    import os, sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from providers.common import normalize, scrape_deadline_from_page  # type: ignore

import requests
import re
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# ============================================================
# METADADOS DO PROVIDER
# ============================================================
PROVIDER = {
    "name": "CAIXA — Fundo Socioambiental (Chamadas abertas)",
    "group": "América Latina / Brasil",
}

# Usado no painel de diagnóstico
URL_HINT = "https://www.caixa.gov.br/sustentabilidade/fundo-socioambiental-caixa/chamadas-abertas/Paginas/default.aspx"

# Flag global de debug (pode pôr True para testar rápido e depois voltar para False)
DEBUG_DEFAULT = True

START_URL = URL_HINT


# ============================================================
# HELPERS
# ============================================================
def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        }
    )
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


def _looks_like_call_title(txt: str) -> bool:
    """Heurística simples pra decidir se um título parece de chamada/editais."""
    t = normalize(txt)
    if not t or len(t) < 5:
        return False
    # costuma ter "edital", "chamada", "chamadas" ou ano
    if "edital" in t or "chamada" in t or "chamadas" in t:
        return True
    # qualquer coisa com ano e alguma palavra-chave
    if re.search(r"20\d{2}", t) and any(
        kw in t
        for kw in (
            "agricultura",
            "economia",
            "circular",
            "socioambiental",
            "socioambientais",
            "fundo",
        )
    ):
        return True
    return False


def _pick_best_link(container: BeautifulSoup, base_url: str, debug_log) -> Optional[str]:
    """
    Dentro de um bloco (div/section/article) escolhe o melhor <a> como link da chamada:
    prioridade pra texto 'Saiba mais', senão primeiro link com 'edital/chamada',
    senão o primeiro link qualquer.
    """
    anchors = container.find_all("a", href=True)
    if not anchors:
        return None

    # 1) 'Saiba mais'
    for a in anchors:
        txt = normalize(a.get_text() or "")
        if txt.startswith("saiba mais"):
            href = _absolutize(a["href"], base_url)
            if href:
                debug_log("link via 'Saiba mais':", href)
                return href

    # 2) anchors com 'edital' ou 'chamada'
    for a in anchors:
        txt = normalize(a.get_text() or "")
        if "edital" in txt or "chamada" in txt:
            href = _absolutize(a["href"], base_url)
            if href:
                debug_log("link via 'edital/chamada':", href)
                return href

    # 3) primeiro link qualquer
    href = _absolutize(anchors[0]["href"], base_url)
    if href:
        debug_log("link via primeiro <a>:", href)
    return href


def _extract_title_for_anchor(a: BeautifulSoup, debug_log) -> str:
    """
    Dado um <a>, tenta achar o título da chamada:
    - heading anterior (h1/h2/h3/h4)
    - ou texto do bloco pai
    """
    # heading anterior
    h = a.find_previous(["h1", "h2", "h3", "h4"])
    if h:
        t = normalize(h.get_text())
        if t:
            debug_log("título via heading anterior:", t)
            return t

    # bloco pai
    block = a
    for _ in range(5):
        if not block:
            break
        if block.name in ("div", "section", "article"):
            txt = normalize(block.get_text())
            if txt:
                # corta se for muito grande
                if len(txt) > 220:
                    txt = txt[:217] + "..."
                debug_log("título via bloco pai:", txt)
                return txt
        block = block.parent

    # fallback: texto do próprio link
    t = normalize(a.get_text())
    debug_log("título via texto do link:", t)
    return t


# ============================================================
# FUNÇÃO PRINCIPAL USADA PELO main.py
# ============================================================
def fetch(regex, cfg, _debug: bool = False) -> List[Dict[str, Any]]:
    """
    Interface usada pelo main.py:
        items = fetch(regex_compilada, cfg_dict)

    Retorna lista de dicts com:
        {source,title,link,deadline,published,agency,region,raw}
    """
    # decide se roda em modo verboso
    debug_cfg = str(cfg.get("CAIXA_FSA_DEBUG", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "sim",
    )
    debug = bool(_debug or DEBUG_DEFAULT or debug_cfg)

    def log(*args):
        if debug:
            print("[CAIXA_FSA]", *args)

    sess = _make_session()
    out: List[Dict[str, Any]] = []
    seen_links = set()

    log("Abrindo página principal:", START_URL)
    try:
        r = sess.get(START_URL, timeout=60, allow_redirects=True)
    except Exception as e:
        log("Erro ao abrir listagem:", e)
        return out

    if not (200 <= r.status_code < 300) or not r.text.strip():
        log("Listagem vazia ou status != 2xx:", r.status_code)
        return out

    soup = BeautifulSoup(r.text, "html.parser")

    # 1) heurística baseada em headings (Edital / Chamada)
    calls_blocks = []

    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        title_txt = normalize(h.get_text() or "")
        if not _looks_like_call_title(title_txt):
            continue

        # sobe até um bloco razoável
        block = h
        for _ in range(5):
            if not block:
                break
            if block.name in ("div", "section", "article"):
                break
            block = block.parent
        if not block:
            block = h

        calls_blocks.append((title_txt, block))

    log("Blocos detectados via headings:", len(calls_blocks))

    def _add_item(link: Optional[str], title: str):
        if not link or not title:
            return
        if regex and not regex.search(title):
            log("Descartado por regex:", title)
            return
        if link in seen_links:
            return
        seen_links.add(link)

        # deadline via helper genérico (pode devolver None)
        dl = scrape_deadline_from_page(link)
        log("OK:", title, "->", link, "| deadline:", dl)

        out.append(
            {
                "source": PROVIDER["name"],
                "title": title,
                "link": link,
                "deadline": dl,
                "published": None,  # site não parece expor data clara
                "agency": "CAIXA",
                "region": "Brasil",
                "raw": {},
            }
        )

    # adiciona itens usando os blocos detectados
    for title_txt, block in calls_blocks:
        link = _pick_best_link(block, START_URL, log)
        if link:
            _add_item(link, title_txt)

    # 2) fallback: anchors 'Saiba mais' que eventualmente não caíram na heurística de heading
    anchors_saiba = soup.find_all("a", href=True)
    for a in anchors_saiba:
        txt = normalize(a.get_text() or "")
        if not txt.startswith("saiba mais"):
            continue
        link = _absolutize(a["href"], START_URL)
        if not link or link in seen_links:
            continue
        title = _extract_title_for_anchor(a, log)
        if not _looks_like_call_title(title):
            # se não parece título de edital, ignora para reduzir ruído
            continue
        _add_item(link, title)

    log("TOTAL de itens coletados:", len(out))
    return out


# ============================================================
# TESTE RÁPIDO STANDALONE
# ============================================================
if __name__ == "__main__":
    """
    Teste rápido de retrievement SEM passar pelo Streamlit.

    Exemplos de uso (a partir da pasta 'python'):

        python providers/latam_caixa_fsa.py
    ou:
        python -m providers.latam_caixa_fsa
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
        print(json.dumps(data[0], ensure_ascii=False, indent=2, default=str))
