from .common import parse_date_any, scrape_deadline_from_page
import requests, streamlit as st

PROVIDER = {"name":"Contracts Finder","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    api_key = st.secrets.get("CONTRACTS_FINDER_API_KEY")
    if not api_key: return []
    url = "https://www.contractsfinder.service.gov.uk/api/rest/2/search_notices"
    payload = {"searchCriteria":{"freeText": regex.pattern.strip("|"), "statuses":["open"], "types":["Opportunity"]}, "pageIndex":0}
    r = requests.post(url, json=payload, headers={"apikey": api_key}, timeout=60)
    if r.status_code != 200: return []
    data = r.json()
    out=[]
    for it in data.get("items",[]):
        title = it.get("title","")
        if title and not regex.search(title): continue
        out.append({"source":PROVIDER["name"],"title": title,
                    "link": it.get("uri",""),
                    "deadline": parse_date_any(it.get("closingDate")) or scrape_deadline_from_page(it.get("uri","")),
                    "published": parse_date_any(it.get("publishDate")),
                    "agency":"UK","region":"UK","raw": it})
    return out
