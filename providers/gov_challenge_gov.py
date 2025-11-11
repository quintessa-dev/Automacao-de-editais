from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"Challenge.gov","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    url = "https://www.challenge.gov"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in href for k in ("challenge","competition","prize")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"US Agencies","region":"US","raw":{}})
    return out
