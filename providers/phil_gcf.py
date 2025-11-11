from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"Green Climate Fund (GCF)","group":"Filantropia"}

def fetch(regex, cfg):
    url = "https://www.greenclimate.fund/work-with-us/opportunities"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in title.lower() for k in ("request for","rfp","concept","call","opportunit")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"GCF","region":"Global","raw":{}})
    return out
