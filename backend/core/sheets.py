# -*- coding: utf-8 -*-
"""
Acesso ao Google Sheets (gspread).

Aqui ficam:
- criação/garantia de abas (config, sources, items, logs, perplexity)
- leitura e escrita com cache simples
- helpers para log em planilha
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Tuple

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from . import config
from .errors import push_error
from datetime import datetime

# Cabeçalho padrão da aba 'items'
ITEMS_HEADER: List[str] = [
    "uid",
    "group",
    "source",
    "title",
    "link",
    "deadline_iso",
    "published_iso",
    "agency",
    "region",
    "raw_json",
    "created_at",
    "seen",
    "status",
    "notes",
    "do_not_show",
]

# Status possíveis, iguais ao Streamlit
STATUS_CHOICES = ["pendente", "verificando", "submetido", "não submetido"]

# Cores de fundo por status (para o frontend)
STATUS_BG = {
    "pendente": "#111111",
    "verificando": "#001a66",
    "submetido": "#0b3d1b",
    "não submetido": "#4a0b0f",
}

# Cores de texto por status (se o frontend quiser usar)
STATUS_COLORS = {
    "pendente": "#FFD166",
    "verificando": "#118AB2",
    "submetido": "#06D6A0",
    "não submetido": "#EF476F",
}


@lru_cache(maxsize=1)
def get_gspread_client() -> gspread.Client:
    """
    Cria um cliente gspread autorizado via OAuth (refresh_token fixo).

    Usa variáveis de ambiente lidas em config.get_google_oauth().
    """
    oauth = config.get_google_oauth()
    creds = Credentials(
        token=None,
        refresh_token=oauth["refresh_token"],
        token_uri=oauth["token_uri"],
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"],
        scopes=config.SCOPES,
    )
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as e:
            push_error("OAuth refresh", e)
            raise
    return gspread.authorize(creds)


@lru_cache(maxsize=1)
def open_sheet():
    """
    Abre a planilha principal por URL e garante que as abas necessárias existam.

    Retorna: (sh, ws_cfg, ws_src, ws_items, ws_log)
    """
    gc = get_gspread_client()
    sh = gc.open_by_url(config.get_sheet_url())

    def ensure(wsname: str, header: List[str]):
        try:
            ws = sh.worksheet(wsname)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(wsname, rows=1000, cols=max(20, len(header)))
            if header:
                ws.append_row(header)
            return ws

        existing = ws.row_values(1)
        if existing != header and header:
            # Mescla cabeçalhos antigos com novos campos
            new_header = existing[:] + [h for h in header if h not in existing]
            ws.resize(
                rows=max(ws.row_count, 1000),
                cols=max(len(new_header), ws.col_count),
            )
            ws.update("1:1", [new_header])
        return ws

    ws_cfg = ensure("config", ["key", "value"])
    ws_src = ensure("sources", ["group", "source", "enabled", "extra_json"])
    ws_items = ensure("items", ITEMS_HEADER)
    ws_log = ensure("logs", ["ts", "level", "msg"])
    return sh, ws_cfg, ws_src, ws_items, ws_log


def values_batch_update(ws, updates: List[Tuple[str, List[List[str]]]]) -> None:
    """
    Aplica um batch_update de valores em ranges arbitrários de uma worksheet.

    'updates' é uma lista de tuplas (range_A1, [[val1, val2, ...]]).
    """
    if not updates:
        return
    body = {
        "valueInputOption": "RAW",
        "data": [{"range": r, "values": vals} for r, vals in updates],
    }
    try:
        ws.spreadsheet.values_batch_update(body)
    except Exception as e:
        push_error("values_batch_update", e)
        raise


def sheet_log(ws_log, level: str, msg: str) -> None:
    """Registra uma linha na aba 'logs' com timestamp, nível e mensagem."""
    try:
        ws_log.append_row([datetime.utcnow().isoformat(), level, msg])
    except Exception as e:
        push_error("sheet_log", e)


@lru_cache(maxsize=1)
def read_items_cached():
    """
    Lê todas as linhas da aba 'items' com cache in-memory.

    Retorna: (header, body)
    - header: lista com os nomes das colunas
    - body: lista de linhas (listas de strings)
    """
    try:
        _, _, _, ws_items, _ = open_sheet()
        rows = ws_items.get_all_values()
    except Exception as e:
        push_error("read_items_cached", e)
        rows = []

    if not rows:
        return ITEMS_HEADER, []

    header = rows[0]
    body = [r + [""] * (len(header) - len(r)) for r in rows[1:]]
    return header, body


def invalidate_items_cache() -> None:
    """Limpa o cache da leitura da aba 'items'."""
    try:
        read_items_cached.cache_clear()
    except Exception:
        pass


def append_items_dedup(
    ws_items, header: List[str], body: List[List[str]], new_rows: List[List[str]]
) -> None:
    """
    Adiciona novas linhas em 'items', garantindo que não haja duplicados por uid.

    Duplicidade é checada na primeira coluna (uid).
    """
    seen = set(r[0] for r in body if r)
    to_add = []
    for r in new_rows:
        if len(r) < len(header):
            r += [""] * (len(header) - len(r))
        if r[0] not in seen:
            to_add.append(r)

    if to_add:
        try:
            ws_items.append_rows(to_add, value_input_option="RAW")
        except Exception as e:
            push_error("append_items_dedup", e)
            return
        invalidate_items_cache()


def read_config() -> Dict[str, str]:
    """
    Lê a aba 'config' e devolve um dicionário key->value.
    """
    _, ws_cfg, _, _, _ = open_sheet()
    rows = ws_cfg.get_all_values()
    data: Dict[str, str] = {}
    for r in rows[1:]:
        if len(r) >= 2 and r[0]:
            data[r[0]] = r[1]
    return data


def upsert_config(key: str, value: str) -> None:
    """
    Atualiza (ou cria) uma linha na aba 'config' para a chave fornecida.
    """
    _, ws_cfg, _, _, _ = open_sheet()
    rows = ws_cfg.get_all_values()
    idx = None
    for i, r in enumerate(rows[1:], start=2):
        if r and r[0] == key:
            idx = i
            break
    if idx:
        ws_cfg.update_cell(idx, 2, value)
    else:
        ws_cfg.append_row([key, value])


def clear_items_sheet() -> None:
    """
    Limpa toda a aba 'items' e recria apenas o cabeçalho padrão.
    """
    _, _, _, ws_items, _ = open_sheet()
    ws_items.clear()
    ws_items.append_row(ITEMS_HEADER)
    invalidate_items_cache()


def get_logs_tail(limit: int = 200) -> List[List[str]]:
    """
    Retorna as últimas 'limit' linhas da aba 'logs' (incluindo header).
    """
    try:
        _, _, _, _, ws_log = open_sheet()
        rows = ws_log.get_all_values()
    except Exception as e:
        push_error("get_logs_tail", e)
        return []

    if not rows:
        return []

    if len(rows) <= limit:
        return rows
    return rows[-limit:]


def ensure_ws_perplexity():
    """
    Garante a aba 'perplexity' com o cabeçalho correto e a retorna.
    """
    sh, *_ = open_sheet()
    header = [
        "timestamp_utc",
        "modo",
        "modelo_api",
        "prompt",
        "parametros_json",
        "tokens_in",
        "tokens_out_estimados",
        "custo_usd_estimado",
        "custo_brl_estimado",
        "resumo",
        "links_citados",
        "json_resposta",
        "erro",
    ]
    try:
        try:
            ws = sh.worksheet("perplexity")
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet("perplexity", rows=1000, cols=max(20, len(header)))
            ws.append_row(header)
        existing = ws.row_values(1)
        if existing != header:
            new_header = existing[:] + [h for h in header if h not in existing]
            ws.resize(
                rows=max(ws.row_count, 1000),
                cols=max(len(new_header), ws.col_count),
            )
            ws.update("1:1", [new_header])
        return ws
    except Exception as e:
        push_error("ensure_ws_perplexity", e)
        raise
