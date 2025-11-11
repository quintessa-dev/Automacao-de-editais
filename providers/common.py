from __future__ import annotations
import re, requests
from bs4 import BeautifulSoup
from datetime import datetime
import dateparser

def parse_date_any(s):
    if not s: return None
    return dateparser.parse(s, settings={"RETURN_AS_TIMEZONE_AWARE": True})

def normalize(x: str) -> str:
    return re.sub(r"\s+", " ", (x or "").strip())

# padrões de data (pt/en) para fallback via scraping leve
DATE_PAT = re.compile(
    r"(?:deadline|closing|closes|close\s*date|prazo|encerramento|fecha(?:mento)?|fecha\s*em)"
    r"[^0-9A-Za-z]{0,20}"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{1,2}\s+[A-Za-zçÇáéíóúãõâêôüÜ]{3,15}\s+\d{4}|\d{4}\-\d{2}\-\d{2})",
    re.I,
)
DATE_ANY = re.compile(
    r"(\d{4}\-\d{2}\-\d{2}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{1,2}\s+[A-Za-zçÇáéíóúãõâêôüÜ]{3,15}\s+\d{4})"
)

def try_fetch(url: str, timeout: int = 25) -> str:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    return ""

def find_deadline_in_text(text: str):
    if not text: return None
    m = DATE_PAT.search(text) or DATE_ANY.search(text)
    if m:
        return parse_date_any(m.group(1))
    return None

def scrape_deadline_from_page(url: str):
    html = try_fetch(url)
    if not html: return None
    soup = BeautifulSoup(html, "html.parser")
    txt = normalize(soup.get_text(" ", strip=True))
    return find_deadline_in_text(txt)

def list_links(url: str, selector: str = "a", attr: str = "href"):
    html = try_fetch(url)
    if not html: return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select(selector):
        t = normalize(a.get_text())
        href = a.get(attr, "")
        if t and href:
            if href.startswith("//"): href = "https:" + href
            if href.startswith("/"):  href = requests.compat.urljoin(url, href)
            out.append((t, href))
    return out