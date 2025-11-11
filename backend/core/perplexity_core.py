# -*- coding: utf-8 -*-
"""
Integração com a API da Perplexity.

Mantém a lógica:
- cálculo aproximado de tokens de entrada
- estimativa de custo (US$ e R$)
- gravação do resultado na aba 'perplexity' se solicitado
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import get_perplexity_api_key
from .errors import push_error
from .sheets import ensure_ws_perplexity


def approx_tokens(txt: str) -> int:
    """
    Estima quantidade de tokens a partir do tamanho da string.

    Mesma heurística usada no Streamlit: len(text)/4.
    """
    if not txt:
        return 0
    return max(1, int(len(txt) / 4))

def count_tokens_from_url(url: str) -> Tuple[int, int, Optional[str]]:
    """
    Faz download do conteúdo do URL e estima a quantidade de tokens.

    Retorna (tokens_est, num_caracteres, erro_str_ou_None).
    A heurística padrão é ~4 caracteres por token.
    Para PDF tenta usar pypdf (se disponível); caso contrário,
    estima a partir do tamanho em bytes.
    """
    try:
        resp = requests.get(url, timeout=30)
    except Exception as e:
        push_error("count_tokens_from_url", e)
        return 0, 0, str(e)

    if resp.status_code >= 400:
        msg = f"{resp.status_code} ao baixar o conteúdo"
        push_error("count_tokens_from_url", Exception(msg))
        return 0, 0, msg

    content_type = (resp.headers.get("Content-Type") or "").lower()
    text = ""
    chars = 0

    # PDF: tenta extrair texto, se não der usa tamanho em bytes
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        try:
            try:
                from io import BytesIO
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(BytesIO(resp.content))
                parts: List[str] = []
                for page in reader.pages:
                    parts.append(page.extract_text() or "")
                text = " ".join(parts)
            except Exception:
                # fallback: usa tamanho do arquivo
                chars = len(resp.content)
                tokens = max(1, chars // 4)
                return tokens, chars, None
        except Exception as e:
            push_error("count_tokens_from_url_pdf", e)
            chars = len(resp.content)
            tokens = max(1, chars // 4)
            return tokens, chars, None
    else:
        # HTML ou texto puro
        try:
            raw = resp.text or ""
        except Exception:
            raw = ""
        if "html" in content_type or "<html" in raw.lower():
            try:
                from bs4 import BeautifulSoup  # type: ignore

                soup = BeautifulSoup(raw, "html.parser")
                text = soup.get_text(separator=" ", strip=True)
            except Exception:
                text = raw
        else:
            text = raw

    chars = len(text)
    tokens = approx_tokens(text)
    return tokens, chars, None

def call_perplexity_chat(
    prompt: str,
    model_id: str,
    temperature: float,
    max_out: int,
    pricing_in: float,
    pricing_out: float,
    usd_brl: float,
    modo_label: str,
    save: bool,
    link_tokens: Optional[int] = None,
    edital_link: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Chama a API da Perplexity com parâmetros fornecidos e,
    opcionalmente, grava o resultado em planilha.

    Observação:
    - O cálculo de custo aqui considera tokens de entrada/saída.
      Para o modelo sonar-deep-research há custos adicionais
      (citation/reasoning/search queries) que NÃO são contabilizados aqui.
      Use este valor como estimativa conservadora.
    """
    api_key = get_perplexity_api_key()
    if not api_key:
        return {"error": "API key da Perplexity não configurada no backend."}

    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    sysmsg = (
        "Você é um pesquisador especializado em editais. "
        "Responda em português, forneça bullets claros e liste as fontes (links)."
    )
    body: Dict[str, Any] = {
        "model": model_id,
        "temperature": float(temperature),
        "max_tokens": int(max_out),
        "return_images": False,
        "messages": [
            {"role": "system", "content": sysmsg},
            {"role": "user", "content": prompt},
        ],
    }

    # Estima tokens de entrada e custo (prompt + tokens do link, se fornecidos)
    extra_link_tokens = int(link_tokens or 0)
    tin_est = approx_tokens(prompt) + max(extra_link_tokens, 0)
    pin = float(pricing_in)
    pout = float(pricing_out)
    custo_usd = (tin_est / 1_000_000.0) * pin + (max_out / 1_000_000.0) * pout
    custo_brl = custo_usd * float(usd_brl)

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=120)
        if resp.status_code >= 400:
            return {"error": f"{resp.status_code} {resp.text}"}
        data = resp.json()
    except Exception as e:
        push_error("call_perplexity_chat", e)
        return {"error": f"exception: {e}"}

    resumo = ""
    links_list: List[str] = []
    try:
        resumo = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        ) or ""
    except Exception:
        resumo = ""

    # Extrai links do texto retornado
    try:
        found = re.findall(r"https?://[^\s)>\]]+", resumo)
        links_list = sorted(set(found))
    except Exception:
        links_list = []

    # Tenta pegar usage real da API, se existir
    usage = data.get("usage") or {}
    tokens_in_real = usage.get("prompt_tokens")
    tokens_out_real = usage.get("completion_tokens")
    tin_for_return = tin_est
    custo_usd_real = custo_usd

    if isinstance(tokens_in_real, int) and isinstance(tokens_out_real, int):
        tin_for_return = tokens_in_real
        custo_usd_real = (
            (tokens_in_real / 1_000_000.0) * pin
            + (tokens_out_real / 1_000_000.0) * pout
        )
        custo_brl = custo_usd_real * float(usd_brl)

    # Grava na planilha se solicitado
    if save:
        try:
            ws = ensure_ws_perplexity()
            from datetime import datetime

            params_json = {
                "temperatura": temperature,
                "max_tokens": max_out,
                "pricing_in": pin,
                "pricing_out": pout,
                "usd_brl": usd_brl,
                "link_tokens": extra_link_tokens,
                "edital_link": edital_link,
            }

            ws.append_row(
                [
                    datetime.utcnow().isoformat(),
                    modo_label,
                    model_id,
                    prompt[:4000],
                    json.dumps(params_json, ensure_ascii=False)[:45000],
                    str(tin_for_return),
                    str(max_out),
                    f"{custo_usd_real:.6f}",
                    f"{custo_brl:.6f}",
                    resumo[:8000],
                    "\n".join(links_list),
                    json.dumps(data, ensure_ascii=False)[:45000],
                    "",
                ]
            )
        except Exception as e:
            push_error("perplexity_append_row", e)

    return {
        "summary": resumo,
        "links": links_list,
        "tokens_in": tin_for_return,
        "estimated_cost_usd": custo_usd_real,
        "estimated_cost_brl": custo_brl,
        "raw": data,
        "error": None,
    }

