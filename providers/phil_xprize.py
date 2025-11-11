from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"XPRIZE","group":"Filantropia"}

def fetch(regex, cfg):
    url = "https://www.xprize.org/prizes"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and ("prize" in title.lower() or "/prizes/" in href):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"XPRIZE","region":"Global","raw":{}})
    return out
