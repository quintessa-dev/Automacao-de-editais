from .common import normalize, list_links, scrape_deadline_from_page

PROVIDER = {"name":"Find a Grant (GOV.UK)","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    url = "https://www.find-government-grants.service.gov.uk/grants"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if regex.search(title) and ("/grants/" in href or "grant" in title.lower()):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"UK Gov","region":"UK","raw":{}})
    return out
