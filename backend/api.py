# -*- coding: utf-8 -*-
"""
API FastAPI do Editais Watcher.

Expõe endpoints REST usados pelo frontend (HTML/JS).

Para rodar localmente:
    pip install fastapi uvicorn gspread google-auth google-auth-oauthlib requests python-dateutil pandas
    uvicorn backend.api:app --reload

E depois abrir http://localhost:8000
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .core.errors import init_error_bus, get_errors
from .core.domain import (
    get_app_config,
    update_config_pairs,
    update_group_regex,
    run_collect,
    get_items_for_group,
    update_items,
    delete_items_by_uids,
    clear_all_items,
    get_diag_providers,
)
from .core.perplexity_core import call_perplexity_chat, count_tokens_from_url

# ---------- MODELOS Pydantic (requests) ----------


class ConfigUpdateItem(BaseModel):
    key: str
    value: str


class ConfigUpdateRequest(BaseModel):
    updates: List[ConfigUpdateItem]


class CollectRequest(BaseModel):
    groups: Optional[List[str]] = None
    min_days: Optional[int] = None


class ItemsUpdateItem(BaseModel):
    uid: str
    seen: bool = False
    status: str = "pendente"
    notes: str = ""
    do_not_show: bool = False


class ItemsUpdateRequest(BaseModel):
    updates: List[ItemsUpdateItem]


class ItemsDeleteRequest(BaseModel):
    uids: List[str]


class DiagRequest(BaseModel):
    re_gov: str = ""
    re_phil: str = ""
    re_latam: str = ""


class PerplexityRequest(BaseModel):
    prompt: str
    modelo_api: str
    modo_label: str
    temperature: float
    max_tokens: int
    pricing_in: float
    pricing_out: float
    usd_brl: float
    save: bool = True
    edital_link: Optional[str] = None
    edital_pages: Optional[int] = None

class TokenCountRequest(BaseModel):
    url: str

# ---------- APP E STATIC ----------

app = FastAPI(title="Editais Watcher API", version="1.0.0")

# Diretório raiz do projeto (assumindo que este arquivo está em backend/api.py)
ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"

# Servir arquivos estáticos (CSS/JS) em /static
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve o index.html do frontend."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=500,
            detail="index.html não encontrado. Verifique a estrutura de pastas.",
        )
    return index_path.read_text(encoding="utf-8")


# ---------- ENDPOINTS DE CONFIG ----------


@app.get("/api/config")
async def api_get_config():
    """
    Retorna configuração geral (aba config, regex por grupo, grupos disponíveis, status, cores).
    """
    init_error_bus()
    cfg = get_app_config()
    return {
        "config": cfg,
        "errors": get_errors(),
    }


@app.post("/api/config")
async def api_update_config(req: ConfigUpdateRequest):
    """
    Atualiza múltiplas chaves na aba 'config'.
    """
    init_error_bus()
    cfg = update_config_pairs(
        [{"key": item.key, "value": item.value} for item in req.updates]
    )
    return {
        "config": cfg,
        "errors": get_errors(),
    }


@app.post("/api/group/regex")
async def api_update_group_regex(payload: Dict[str, Any]):
    """
    Atualiza o regex de um grupo específico.

    Body esperado: { "group": "...", "regex": "..." }
    """
    group = payload.get("group")
    regex = payload.get("regex", "")
    if not group:
        raise HTTPException(status_code=400, detail="Campo 'group' é obrigatório.")

    init_error_bus()
    cfg = update_group_regex(group, regex)
    return {
        "config": cfg,
        "errors": get_errors(),
    }


# ---------- ENDPOINTS DE ITENS / COLETA ----------


@app.post("/api/collect")
async def api_collect(req: CollectRequest):
    """
    Executa coleta de providers, grava na planilha e retorna estatísticas.

    - groups: lista de grupos a coletar (ou None para todos)
    - min_days: opcional; se None, usa valor salvo em config.MIN_DAYS (ou default)
    """
    init_error_bus()
    cfg = get_app_config()["config"]
    if req.min_days is not None:
        min_days = int(req.min_days)
    else:
        min_days = int(cfg.get("MIN_DAYS", "21"))

    result = run_collect(min_days=min_days, groups_filter=req.groups)
    return {
        "result": result,
        "errors": get_errors(),
    }


@app.get("/api/items")
async def api_get_items(group: str, status: Optional[str] = None):
    """
    Retorna itens de um grupo, agrupados por fonte, com filtro opcional de status.
    """
    init_error_bus()
    data = get_items_for_group(group, status_filter=status)
    return {
        "items": data,
        "errors": get_errors(),
    }


@app.post("/api/items/update")
async def api_update_items(req: ItemsUpdateRequest):
    """
    Aplica atualizações em itens (seen, status, notes, do_not_show) com base em uid.
    """
    init_error_bus()
    updates_dicts = [item.dict() for item in req.updates]
    result = update_items(updates_dicts)
    return {
        "result": result,
        "errors": get_errors(),
    }


@app.post("/api/items/delete")
async def api_delete_items(req: ItemsDeleteRequest):
    """
    Remove itens da planilha a partir de uma lista de uids.
    """
    init_error_bus()
    result = delete_items_by_uids(req.uids)
    return {
        "result": result,
        "errors": get_errors(),
    }


@app.post("/api/items/clear")
async def api_clear_items():
    """
    Limpa todos os itens (mantém apenas o cabeçalho).
    """
    init_error_bus()
    result = clear_all_items()
    return {
        "result": result,
        "errors": get_errors(),
    }


# ---------- ENDPOINTS DE DIAGNÓSTICO ----------


@app.post("/api/diag/providers")
async def api_diag_providers(req: DiagRequest):
    """
    Executa diagnóstico dos providers (similar à aba de diagnóstico).

    Permite informar regex customizado para GOVERNO/PHIL/LATAM,
    ou usar valores vazios para cair nos defaults.
    """
    init_error_bus()
    data = get_diag_providers(req.re_gov, req.re_phil, req.re_latam)
    return {
        "diag": data,
        "errors": get_errors(),
    }


@app.get("/api/diag/logs")
async def api_diag_logs():
    """
    Retorna apenas os logs da aba 'logs' (últimas 200 linhas),
    caso o frontend queira exibir separado.
    """
    init_error_bus()
    data = get_diag_providers("", "", "")  # reaproveita função (já traz logs)
    return {
        "logs": data["logs"],
        "errors": get_errors(),
    }


# ---------- ENDPOINT PERPLEXITY ----------
@app.post("/api/perplexity/count_tokens")
async def api_perplexity_count_tokens(req: TokenCountRequest):
    """
    Faz download do conteúdo do link e retorna uma estimativa de tokens.
    Usa a mesma heurística (~4 caracteres por token).
    """
    init_error_bus()
    tokens, chars, error = count_tokens_from_url(req.url)
    return {
        "ok": error is None,
        "tokens": tokens,
        "characters": chars,
        "error": error,
        "errors": get_errors(),
    }

@app.post("/api/perplexity/search")
async def api_perplexity_search(req: PerplexityRequest):
    """
    Chama a Perplexity com os parâmetros enviados pelo frontend.

    O cálculo de custo é refeito aqui com base em:
    - pricing_in (US$/1M tokens entrada)
    - pricing_out (US$/1M tokens saída)
    - usd_brl (cotação)
    - link_tokens (tokens estimados do conteúdo do link, se fornecido)
    """
    init_error_bus()
    result = call_perplexity_chat(
        prompt=req.prompt,
        model_id=req.modelo_api,
        temperature=req.temperature,
        max_out=req.max_tokens,
        pricing_in=req.pricing_in,
        pricing_out=req.pricing_out,
        usd_brl=req.usd_brl,
        modo_label=req.modo_label,
        save=req.save,
        link_tokens=req.link_tokens,
        edital_link=req.edital_link,
    )
    return {
        "result": result,
        "errors": get_errors(),
    }
