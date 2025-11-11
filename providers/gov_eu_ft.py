from .common import normalize
import requests
from bs4 import BeautifulSoup

PROVIDER = {"name":"EU Funding & Tenders","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    url = "https://ec.europa.eu/info/funding-tenders/opportunities/data/topic-list.html"
    r = requests.get(url, timeout=60); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out=[]
    for a in soup.find_all("a"):
        code = normalize(a.get_text())
        if code and regex.search(code):
            out.append({"source":PROVIDER["name"],"title":code,
                        "link":"https://ec.europa.eu/info/funding-tenders/opportunities/portal/",
                        "deadline":None,"published":None,"agency":"European Commission","region":"EU","raw":{"topic_code":code}})
    return out
