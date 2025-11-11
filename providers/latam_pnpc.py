# -*- coding: utf-8 -*-
from __future__ import annotations

from .common import normalize  # mantém compat; não usamos scrape_deadline aqui
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from urllib.parse import urlencode

PROVIDER = {"name": "PNCP — API (Licitações + Contratações)", "group": "América Latina / Brasil"}

# --- ENDPOINTS OFICIAIS (consulta pública PNCP) ---
BASE_CONSULTA = "https://pncp.gov.br/api/consulta/v1"
EP_PUBLICACAO = f"{BASE_CONSULTA}/contratacoes/publicacao"  # OK
EP_PROPOSTA   = f"{BASE_CONSULTA}/contratacoes/proposta"    # OK
# Rotas acima confirmadas no catálogo/Swagger. Não use /licitacoes/publicacao.  # (404)  :contentReference[oaicite:1]{index=1}

# paginação
PAGE_SIZE = 50
MAX_PAGES = 50

# modalidades exigidas no caso do seu uso (2 e 3)
LIC_MODALIDADES = (2, 3)

HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (EditaisWatcher)"}

def _today_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")

def _days_ago_yyyymmdd(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")

def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # aceita "YYYY-MM-DD" ou ISO completo
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _link_busca(numero_controle: str, termo: str = "") -> str:
    # Fallback confiável: abre app de editais filtrando pelo número/termo
    base = "https://pncp.gov.br/app/editais"
    q = numero_controle or (termo[:120] if termo else "")
    return f"{base}?{urlencode({'pagina':1,'q':q,'status':'todos'})}"

def _paginate(url: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        qp = dict(params)
        qp["pagina"] = page
        qp["tamanhoPagina"] = PAGE_SIZE
        r = requests.get(url, params=qp, headers=HEADERS, timeout=60)
        if r.status_code == 204:
            break
        r.raise_for_status()
        data = r.json() or {}
        lote = data.get("data") or []
        if not lote:
            break
        out.extend(lote)
        total = int(data.get("totalPaginas") or 0)
        if page >= total or len(lote) < PAGE_SIZE:
            break
    return out

def _title(it: Dict[str, Any]) -> str:
    # nomes mais comuns na consulta PNCP
    objeto = (it.get("objetoCompra") or it.get("objeto") or "").strip()
    numero = (it.get("numeroControlePNCP") or "").strip()
    t = normalize(objeto) if objeto else ""
    if numero and (not t or numero not in t):
        t = (t + " — " + numero).strip(" —")
    return t or "Edital PNCP"

def _agency(it: Dict[str, Any]) -> str:
    ent = it.get("orgaoEntidade") or {}
    return ent.get("razaoSocial") or ent.get("nome") or "PNCP"

def _region(it: Dict[str, Any]) -> str:
    uo = it.get("unidadeOrgao") or {}
    return uo.get("ufSigla") or "Brasil"

def _item_to_out(it: Dict[str, Any], regex):
    numero = (it.get("numeroControlePNCP") or "").strip()
    titulo = _title(it)
    if regex and not regex.search(normalize(titulo)):
        # se regex estiver setada e não casar, descarta
        return None

    # publicadas / propostas costumam trazer:
    pub = _parse_dt(it.get("dataPublicacaoPncp") or it.get("dataPublicacao"))
    dl  = _parse_dt(it.get("dataEncerramentoProposta") or it.get("dataFimRecebimentoProposta"))

    link_primario = (it.get("linkSistemaOrigem") or "").strip()
    link = link_primario if link_primario.startswith(("http://","https://")) else _link_busca(numero, titulo)

    return {
        "source": PROVIDER["name"],
        "title": titulo[:180],
        "link": link,
        "deadline": dl,
        "published": pub,
        "agency": _agency(it),
        "region": _region(it),
        "raw": it,
    }

def fetch(regex, cfg):
    # últimos 30 dias por padrão
    dini = _days_ago_yyyymmdd(30)
    dfim = _today_yyyymmdd()

    results: List[Dict[str, Any]] = []
    seen_links: set[str] = set()

    # 1) PUBLICAÇÕES (exige modalidade)
    for mod in LIC_MODALIDADES:
        params = {"dataInicial": dini, "dataFinal": dfim, "codigoModalidadeContratacao": mod}
        for it in _paginate(EP_PUBLICACAO, params):
            out_item = _item_to_out(it, regex)
            if out_item and out_item["link"] not in seen_links:
                results.append(out_item); seen_links.add(out_item["link"])

    # 2) PROPOSTAS EM ABERTO (até hoje) — também exige modalidade
    for mod in LIC_MODALIDADES:
        params = {"dataFinal": dfim, "codigoModalidadeContratacao": mod}
        for it in _paginate(EP_PROPOSTA, params):
            out_item = _item_to_out(it, regex)
            if out_item and out_item["link"] not in seen_links:
                results.append(out_item); seen_links.add(out_item["link"])

    return results
