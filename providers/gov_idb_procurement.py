from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"IDB Project Procurement/BEO","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    url = "https://projectprocurement.iadb.org/en"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in href for k in ("procurement","opportunities","tenders","bank-executed")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"IDB","region":"LatAm","raw":{}})
    return out
