from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"World Bank Procurement","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    # Página pública agregada (avaliação leve). Para usar Socrata, integre catálogos específicos depois.
    url = "https://projects.worldbank.org/en/projects-operations/procurement"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and ("procurement" in href or "tenders" in href or "notice" in href):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"World Bank","region":"Global","raw":{}})
    return out
