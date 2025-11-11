from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"AfDB Procurement","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    url = "https://www.afdb.org/en/projects-and-operations/procurement"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in href for k in ("procurement","tenders","opportunities","request","rfp")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"AfDB","region":"Africa","raw":{}})
    return out
