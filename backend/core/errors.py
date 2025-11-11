# -*- coding: utf-8 -*-
"""
Coletor de erros simples (Error Bus).

Antes de cada operação 'grande' (ex.: coleta, diag, perplexity),
o backend deve chamar `init_error_bus()`.

Todas as funções de domínio chamam `push_error()` em caso de exceção,
e o endpoint pode ler depois com `get_errors()`.
"""

import traceback
from datetime import datetime
from typing import List, Dict, Any

_error_bus: List[Dict[str, Any]] = []


def init_error_bus() -> None:
    """Limpa a lista de erros da execução atual."""
    global _error_bus
    _error_bus = []


def push_error(where: str, exc: Exception) -> None:
    """
    Registra um erro com local, mensagem e stacktrace.

    As funções de domínio devem chamar isso em vez de dar print.
    """
    global _error_bus
    stack = traceback.format_exc()
    msg = f"{type(exc).__name__}: {exc}"
    _error_bus.append(
        {
            "ts": datetime.utcnow().isoformat(),
            "where": where,
            "msg": msg,
            "stack": stack,
        }
    )


def get_errors() -> List[Dict[str, Any]]:
    """Retorna a lista de erros registrados nesta execução."""
    return list(_error_bus)
