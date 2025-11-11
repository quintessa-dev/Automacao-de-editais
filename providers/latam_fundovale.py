from .common import list_links, scrape_deadline_from_page

PROVIDER = {"name":"Fundo Vale","group":"América Latina / Brasil"}

def fetch(regex, cfg):
    url = "https://www.fundovale.org/"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        t=title.lower()
        if regex.search(title) and any(k in t for k in ("edital","chamada","parceria","seleção")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"Fundo Vale","region":"Brasil","raw":{}})
    return out
