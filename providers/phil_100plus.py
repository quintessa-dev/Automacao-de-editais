from .common import list_links, scrape_deadline_from_page

PROVIDER = {"name":"100+ Accelerator","group":"Filantropia"}

def fetch(regex, cfg):
    url = "https://www.100accelerator.com"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and ("apply" in title.lower() or "challenge" in title.lower()):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"AB InBev & Partners","region":"Global","raw":{}})
    return out
