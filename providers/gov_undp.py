from .common import parse_date_any, normalize
import feedparser, re

PROVIDER = {"name":"UNDP Procurement","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    feed = feedparser.parse("https://procurement-notices.undp.org/proc_notices_rss_feed.cfm")
    out=[]
    for e in feed.entries:
        txt = normalize(f"{e.get('title','')} {e.get('summary','')}")
        if not regex.search(txt): continue
        dlm = re.search(r"(deadline|closing|prazo)[^0-9]{0,20}(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[0-9]{2}/[0-9]{2}/[0-9]{4})", txt, re.I)
        out.append({"source":PROVIDER["name"],"title": normalize(e.get("title","")),
                    "link": e.get("link",""),
                    "deadline": parse_date_any(dlm.group(2)) if dlm else None,
                    "published": parse_date_any(e.get("published")),
                    "agency":"UNDP","region":"Global","raw":{"rss":"undp"}})
    return out
