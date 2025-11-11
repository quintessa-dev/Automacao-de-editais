from .common import normalize, list_links, scrape_deadline_from_page
import streamlit as st

PROVIDER = {"name":"UNGM","group":"Governo/Multilaterais"}

def fetch(regex, cfg):
    # Sem API aberta universal; raspagem leve da página de oportunidades públicas
    url = "https://www.ungm.org/Public/Notice"
    pairs = list_links(url, "a")
    out=[]
    for title, href in pairs:
        if ("Notice" in href or "/Public/Notice/" in href) and regex.search(title):
            out.append({"source":PROVIDER["name"],"title":title[:180],
                        "link":href,"deadline":scrape_deadline_from_page(href),
                        "published":None,"agency":"UN System","region":"Global","raw":{}})
    return out