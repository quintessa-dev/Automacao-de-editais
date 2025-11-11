from .common import normalize, scrape_deadline_from_page
import requests
from bs4 import BeautifulSoup

PROVIDER = {"name":"Wellcome","group":"Filantropia"}

def fetch(regex, cfg):
    url = "https://wellcome.org/grant-funding/schemes"
    r = requests.get(url, timeout=60); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out=[]
    for a in soup.select("a"):
        title = normalize(a.get_text()); href  = a.get("href","")
        if not href or not title: continue
        if regex.search(f"{title} {href}"):
            full = "https://wellcome.org"+href if href.startswith("/") else href
            dl = scrape_deadline_from_page(full)
            out.append({"source":PROVIDER["name"],"title": title,
                        "link": full, "deadline": dl, "published": None,
                        "agency":"Wellcome","region":"Global","raw":{}})
    return out
