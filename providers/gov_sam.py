from .common import parse_date_any
import requests, streamlit as st

PROVIDER = {"name":"SAM.gov (Contract Opportunities)","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    api_key = st.secrets.get("SAM_API_KEY")
    if not api_key: return []
    url = "https://api.sam.gov/prod/opportunities/v1/search"
    params = {
        "api_key": api_key,
        "limit": 50,
        "q": regex.pattern.strip("|"),
        "ptype": "o"  # opportunities
    }
    r = requests.get(url, params=params, timeout=60)
    if r.status_code != 200: return []
    data = r.json()
    out=[]
    for it in data.get("opportunitiesData", []):
        out.append({
            "source": PROVIDER["name"],
            "title": it.get("title",""),
            "link": it.get("uiLink","") or it.get("url",""),
            "deadline": parse_date_any(it.get("responseDate") or it.get("archiveDate")),
            "published": parse_date_any(it.get("postedDate")),
            "agency": (it.get("department","") or it.get("office","")),
            "region": "US",
            "raw": it
        })
    return out
