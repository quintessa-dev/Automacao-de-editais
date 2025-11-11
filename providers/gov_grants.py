from .common import parse_date_any
import requests

PROVIDER = {"name":"Grants.gov","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    status = cfg.get("GRANTS_STATUS","posted")
    url = "https://api.grants.gov/v1/api/search2"
    payload = {"startRecordNum":0,"sortBy":"closeDate|asc","oppStatuses":status,"keyword":regex.pattern.strip("|"),"rows":100}
    r = requests.post(url, json=payload, timeout=60); r.raise_for_status()
    data = r.json()
    out=[]
    for it in data.get("oppHits", []):
        out.append({
            "source": PROVIDER["name"],
            "title": it.get("title",""),
            "link": f"https://www.grants.gov/search-results-detail/{it.get('id')}",
            "deadline": parse_date_any(it.get("closeDate")),
            "published": parse_date_any(it.get("openDate")),
            "agency": it.get("agency",""),
            "region": "US",
            "raw": it
        })
    return out
