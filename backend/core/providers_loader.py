# -*- coding: utf-8 -*-
"""
Carregamento dinâmico de providers (providers.*).

Aqui é feita a descoberta de módulos que tenham:
- atributo PROVIDER (dict com 'group' e 'name')
- função fetch(regex, cfg) -> List[dict]
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from functools import lru_cache
from typing import List

from .errors import push_error
from .sheets import open_sheet, sheet_log


@lru_cache(maxsize=1)
def discover_providers():
    """
    Vasculha o pacote 'providers' e retorna uma lista de módulos
    que possuam PROVIDER e função fetch(...).

    Mantém o comportamento genérico do código original.
    """
    mods: List[object] = []
    try:
        import providers  # pacote onde estão os arquivos providers/*.py
    except ImportError as e:
        push_error("discover_providers import providers", e)
        return []

    seen = set()

    # 1) percorre subpacotes e módulos via pkgutil
    for finder, name, ispkg in pkgutil.walk_packages(
        providers.__path__, providers.__name__ + "."
    ):
        if ispkg:
            continue
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "PROVIDER") and callable(getattr(mod, "fetch", None)):
                mods.append(mod)
                seen.add(name)
        except Exception as e:
            push_error(f"Import provider {name}", e)
            try:
                _, _, _, _, ws_log = open_sheet()
                sheet_log(
                    ws_log,
                    "ERROR",
                    f"Import provider {name}: {e}",
                )
            except Exception:
                pass

    # 2) fallback: varrer .py diretos dentro do diretório do pacote
    try:
        import pathlib

        pkg_dir = pathlib.Path(providers.__file__).parent
        for p in pkg_dir.glob("*.py"):
            if p.name.startswith("_") or p.name == "__init__.py":
                continue
            name = f"{providers.__name__}.{p.stem}"
            if name in seen:
                continue
            try:
                mod = importlib.import_module(name)
                if hasattr(mod, "PROVIDER") and callable(getattr(mod, "fetch", None)):
                    mods.append(mod)
                    seen.add(name)
            except Exception as e:
                push_error(f"Import provider {name}", e)
                try:
                    _, _, _, _, ws_log = open_sheet()
                    sheet_log(
                        ws_log,
                        "ERROR",
                        f"Import provider {name}: {e}",
                    )
                except Exception:
                    pass
    except Exception:
        pass

    # Ordena por grupo / nome para exibir consistente
    mods.sort(key=lambda x: (x.PROVIDER.get("group", ""), x.PROVIDER.get("name", "")))

    # Loga o que foi carregado
    try:
        _, _, _, _, ws_log = open_sheet()
        sheet_log(
            ws_log,
            "INFO",
            "providers_loaded: "
            + str(
                [
                    {
                        "group": m.PROVIDER.get("group", ""),
                        "name": m.PROVIDER.get("name", ""),
                    }
                    for m in mods
                ]
            )[:45000],
        )
    except Exception:
        pass

    return mods


def load_providers():
    """Alias simples para discover_providers()."""
    return discover_providers()


@lru_cache(maxsize=1)
def get_available_groups() -> list[str]:
    """
    Retorna a lista de grupos disponíveis, misturando base fixa
    com grupos descobertos nos providers.
    """
    base = ["Governo/Multilaterais", "Filantropia", "América Latina / Brasil"]
    try:
        mods = load_providers()
        groups = {
            m.PROVIDER.get("group", "")
            for m in mods
            if m.PROVIDER.get("group", "").strip()
        }
    except Exception:
        groups = set()
    groups.update(base)
    return sorted(groups, key=lambda s: s.lower())


def reload_provider_modules() -> None:
    """
    Recarrega módulos providers.* e limpa caches de descoberta/grupos.

    Útil quando se adiciona um novo provider sem reiniciar o backend.
    """
    try:
        import providers

        for mname, mobj in list(sys.modules.items()):
            if mname.startswith("providers.") and mobj:
                try:
                    importlib.reload(mobj)
                except Exception:
                    pass
        try:
            discover_providers.cache_clear()
        except Exception:
            pass
        try:
            get_available_groups.cache_clear()
        except Exception:
            pass
    except Exception as e:
        push_error("reload_providers_modules", e)
