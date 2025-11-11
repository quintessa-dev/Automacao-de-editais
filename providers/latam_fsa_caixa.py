from .common import list_links, scrape_deadline_from_page

PROVIDER = {"name":"Fundo Socioambiental CAIXA","group":"América Latina / Brasil"}

def fetch(regex, cfg):
    url = "https://www.caixa.gov.br/poder-publico/programas-sociais/fundo-socioambiental/Paginas/default.aspx"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in title.lower() for k in ("edital","seleção","chamada")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"CAIXA","region":"Brasil","raw":{}})
    return out
