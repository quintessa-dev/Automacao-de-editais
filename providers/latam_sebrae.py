from .common import list_links, scrape_deadline_from_page

PROVIDER = {"name":"SEBRAE Editais/Programas","group":"América Latina / Brasil"}

def fetch(regex, cfg):
    url = "https://www.sebrae.com.br/sites/PortalSebrae/ufs/df/sebraeaz/editais"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in title.lower() for k in ("edital","programa","seleção","chamada")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"SEBRAE","region":"Brasil","raw":{}})
    return out
