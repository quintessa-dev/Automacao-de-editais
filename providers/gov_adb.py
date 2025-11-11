from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"ADB (CSRN/Procurement)","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    url = "https://www.adb.org/projects/tenders"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and any(k in href for k in ("tenders","csrn","procurement","notice")):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"ADB","region":"Asia","raw":{}})
    return out
