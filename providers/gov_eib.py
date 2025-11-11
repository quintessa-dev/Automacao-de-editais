from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"EIB Procurement","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    url = "https://www.eib.org/en/about/procurement/index.htm"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in href for k in ("procurement","tenders","calls","notice")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"EIB","region":"EU","raw":{}})
    return out
