# -*- coding: utf-8 -*-
"""
Lógica de domínio principal do Editais Watcher:

- Canonização de grupos e regex por grupo
- Coleta de itens via providers
- Migração de links relativos
- Leitura e escrita de itens na planilha
- Geração de dados para UI (itens por grupo, diag, etc.)
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

from dateutil import parser as date_parser

from .errors import push_error
from .sheets import (
    ITEMS_HEADER,
    STATUS_CHOICES,
    STATUS_BG,
    STATUS_COLORS,
    open_sheet,
    values_batch_update,
    read_items_cached,
    invalidate_items_cache,
    append_items_dedup,
    read_config,
    upsert_config,
    clear_items_sheet,
    sheet_log,
    get_logs_tail,
)
from .providers_loader import load_providers, reload_provider_modules, get_available_groups


# Base conhecida por fonte para absolutizar links relativos (BNDES)
PROVIDER_BASE = {
    "BNDES Chamadas": "https://www.bndes.gov.br/wps/portal/site/home/mercado-de-capitais/fundos-de-investimentos/chamadas-publicas-para-selecao-de-fundos"  # noqa: E501
}


def absolutize_for_source(href: str, source: str) -> str:
    """
    Se o link vier relativo (ex.: '?1dmy=...'), converte para absoluto usando a base da fonte.
    """
    if not href:
        return href
    u = href.strip()
    if urlparse(u).scheme in ("http", "https"):
        return u
    base = PROVIDER_BASE.get(source, "https://www.bndes.gov.br/")
    return urljoin(base, u)


def sha_id(*parts: str) -> str:
    """Gera um hash estável (uid) a partir de partes arbitrárias."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def col_letter(i: int) -> str:
    """
    Converte índice zero-based de coluna em letra(s) de coluna (A, B, ..., AA, AB...).
    """
    s = ""
    while True:
        i, r = divmod(i, 26)
        s = chr(65 + r) + s
        if i == 0:
            break
        i -= 1
    return s


def _to_iso(v: Any) -> str:
    """
    Converte datetime/date/string para ISO (robusto).

    Mantém a lógica original de tentar isoformat() e depois dateutil.
    """
    if not v:
        return ""
    if isinstance(v, str):
        return v
    try:
        return v.isoformat()
    except Exception:
        try:
            return date_parser.parse(str(v)).isoformat()
        except Exception:
            return str(v)


def within_min_days(deadline_iso: Optional[str], min_days: int) -> bool:
    """
    Verifica se a data de deadline está a pelo menos 'min_days' dias no futuro.

    Se não conseguir interpretar ou não houver deadline, considera True
    (mantém comportamento permissivo).
    """
    if not deadline_iso:
        return True
    try:
        dt = date_parser.isoparse(deadline_iso)
    except Exception:
        return True
    now = datetime.now(tz=dt.tzinfo)
    return (dt - now).days >= min_days


def _compile_re(val: Optional[str], fallback: str = r".+") -> re.Pattern:
    """
    Compila regex, caindo para 'fallback' se regex estiver vazia ou inválida.
    """
    try:
        pat = (val or "").strip()
        if pat == "":
            pat = fallback
        return re.compile(pat, re.I)
    except re.error:
        return re.compile(fallback, re.I)


# ---------- canonização de nomes de grupo ----------
def _canon_group(s: str) -> str:
    """
    Normaliza o nome do grupo remo vendo acentos, espaços extras etc.
    Facilita comparar strings de grupos.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _regex_key_for_group(group_name: str) -> str:
    """
    Mapeia o nome do grupo para a chave de configuração (RE_XXX ou RE_GOV/RE_PHIL/RE_LATAM).
    """
    if _canon_group(group_name) == _canon_group("Governo/Multilaterais"):
        return "RE_GOV"
    if _canon_group(group_name) == _canon_group("Filantropia"):
        return "RE_PHIL"
    if _canon_group(group_name) == _canon_group("América Latina / Brasil"):
        return "RE_LATAM"
    return f"RE_{hashlib.sha1(group_name.encode()).hexdigest()[:6].upper()}"


# Defaults para regex por grupo (iguais ao código original)
DEFAULT_REGEX = {
    "RE_GOV": r"bioeconom(y|ia)|biodiversit(y|ade)|forest|amaz(o|ô)nia|innovation|accelerat(or|ora)|impact",  # noqa: E501
    "RE_PHIL": r"(climate|biodiversit|health|science|equitable|innovation|impact|accelerator)",
    "RE_LATAM": r"(bioeconom|biodivers|amaz[oô]nia|floresta|inova|acelera|impacto|tecnologia)",
}


def _migrate_relative_links() -> int:
    """
    Conserta links relativos já salvos (ex.: '?1dmy=...') na aba 'items'.

    Retorna a quantidade de links corrigidos.
    """
    try:
        _, _, _, ws_items_admin, _ = open_sheet()
        rows = ws_items_admin.get_all_values()
        if not rows:
            return 0
        header = rows[0]
        body = rows[1:]
        if "link" not in header or "source" not in header:
            return 0
        idx_link = header.index("link")
        idx_source = header.index("source")
        updates: List[Tuple[str, List[List[str]]]] = []
        for i, r in enumerate(body, start=2):
            if len(r) <= max(idx_link, idx_source):
                continue
            old_link = (r[idx_link] or "").strip()
            source = (r[idx_source] or "").strip()
            if not old_link:
                continue
            if urlparse(old_link).scheme in ("http", "https"):
                continue
            new_link = absolutize_for_source(old_link, source)
            if new_link and new_link != old_link:
                cell = f"items!{col_letter(idx_link)}{i}"
                updates.append((cell, [[new_link]]))
        if updates:
            values_batch_update(ws_items_admin, updates)
            invalidate_items_cache()
        return len(updates)
    except Exception as e:
        push_error("migrate_relative_links", e)
        return 0


def add_row(rows: List[List[str]], group: str, it: Dict[str, Any]) -> None:
    """
    Converte um item coletado de provider em uma linha para aba 'items'
    usando o schema padrão.
    """
    deadline_iso = _to_iso(it.get("deadline"))
    published_iso = _to_iso(it.get("published"))
    rows.append(
        [
            sha_id(
                group,
                it.get("source", ""),
                it.get("title", ""),
                it.get("link", ""),
            ),
            group,
            it.get("source", ""),
            it.get("title", ""),
            it.get("link", ""),
            deadline_iso,
            published_iso,
            it.get("agency", ""),
            it.get("region", ""),
            json.dumps(it.get("raw", {}), ensure_ascii=False),
            datetime.utcnow().isoformat(),
            "",
            "pendente",
            "",
            "",
        ]
    )


def run_collect(
    min_days: int,
    groups_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Executa a coleta nos providers, grava novos itens na planilha
    e retorna estatísticas da execução.

    - min_days: prazo mínimo em dias para considerar os editais
    - groups_filter: lista de grupos a coletar (ou None para todos)
    """
    # Recarrega providers (para pegar novos arquivos sem reiniciar)
    reload_provider_modules()

    fixed_links = _migrate_relative_links()

    providers_all = load_providers()

    if groups_filter:
        filter_norm = {_canon_group(g) for g in groups_filter}
        providers = [
            p
            for p in providers_all
            if _canon_group(p.PROVIDER.get("group", "")) in filter_norm
        ]
    else:
        providers = providers_all[:]

    cfg = read_config()

    # Mapa de regex por grupo
    re_map: Dict[str, re.Pattern] = {}
    all_groups = {p.PROVIDER.get("group", "") for p in providers_all}
    for g in all_groups:
        key = _regex_key_for_group(g)
        base_pattern = cfg.get(key) or DEFAULT_REGEX.get(key, r".+")
        fallback = DEFAULT_REGEX.get(key, r".+")
        re_map[g] = _compile_re(base_pattern, fallback=fallback)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    provider_stats: List[Dict[str, Any]] = []

    total = max(len(providers), 1)
    step = 0

    for p in providers:
        gname = p.PROVIDER.get("group", "")
        grouped.setdefault(gname, [])
        src_name = p.PROVIDER.get("name", "(sem nome)")
        try:
            rgx = re_map.get(
                gname,
                _compile_re(DEFAULT_REGEX.get(_regex_key_for_group(gname), r".+")),
            )
            items_raw = p.fetch(rgx, cfg) or []
            n_raw = len(items_raw)

            grouped[gname].extend(items_raw)

            # Conta quantos passam no filtro de prazo mínimo
            n_pos_prazo = 0
            for it in items_raw:
                dl_iso = _to_iso(it.get("deadline"))
                if within_min_days(dl_iso, int(min_days)):
                    n_pos_prazo += 1

            provider_stats.append(
                {
                    "grupo": gname,
                    "fonte": src_name,
                    "itens_fetch": n_raw,
                    "itens_pos_prazo": n_pos_prazo,
                }
            )

        except Exception as e:
            push_error(f"{src_name} fetch", e)
            provider_stats.append(
                {
                    "grupo": gname,
                    "fonte": src_name,
                    "itens_fetch": "erro",
                    "itens_pos_prazo": "erro",
                }
            )

        step += 1

    # Loga estatísticas na aba 'logs'
    if provider_stats:
        try:
            _, _, _, _, ws_log = open_sheet()
            sheet_log(
                ws_log,
                "INFO",
                "provider_stats: " + json.dumps(provider_stats, ensure_ascii=False)[:45000],
            )
        except Exception:
            pass

    # Grava novos itens na aba 'items'
    try:
        header, body = read_items_cached()
        idx_dns = header.index("do_not_show") if "do_not_show" in header else None
        uids_block = set()
        if idx_dns is not None:
            uids_block = {
                r[0] for r in body if len(r) > idx_dns and r[idx_dns] == "1"
            }

        rows_to_add: List[List[str]] = []
        for gname, items in grouped.items():
            for it in items:
                dl_iso = _to_iso(it.get("deadline"))
                if not within_min_days(dl_iso, int(min_days)):
                    continue
                add_row(rows_to_add, gname, it)

        filtered_rows = [r for r in rows_to_add if r[0] not in uids_block]
        _, _, _, ws_items, _ = open_sheet()
        append_items_dedup(ws_items, header, body, filtered_rows)
        new_count = len(filtered_rows)
    except Exception as e:
        push_error("gravação planilha", e)
        new_count = 0

    return {
        "fixed_links": fixed_links,
        "provider_stats": provider_stats,
        "new_items": new_count,
    }


def get_app_config() -> Dict[str, Any]:
    """
    Retorna a configuração geral para o frontend:

    - config cru (aba 'config')
    - defaults de regex
    - grupos disponíveis
    - regex por grupo (já resolvida)
    - status / cores
    """
    cfg = read_config()
    groups = get_available_groups()

    regex_by_group: Dict[str, str] = {}
    for g in groups:
        key = _regex_key_for_group(g)
        regex_by_group[g] = cfg.get(key) or DEFAULT_REGEX.get(key, "")

    return {
        "config": cfg,
        "defaults": DEFAULT_REGEX,
        "available_groups": groups,
        "regex_by_group": regex_by_group,
        "status_choices": STATUS_CHOICES,
        "status_bg": STATUS_BG,
        "status_colors": STATUS_COLORS,
    }


def update_config_pairs(updates: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Atualiza várias chaves na aba 'config' de uma vez.

    'updates' deve ser lista de dicts com 'key' e 'value'.
    """
    for item in updates:
        k = item.get("key")
        v = item.get("value", "")
        if not k:
            continue
        upsert_config(k, str(v))
    return get_app_config()


def update_group_regex(group: str, regex: str) -> Dict[str, Any]:
    """
    Atualiza o regex para um grupo específico (mapeando para chave RE_...).

    Retorna a config atualizada.
    """
    key = _regex_key_for_group(group)
    upsert_config(key, regex)
    return get_app_config()


def get_items_for_group(group: str, status_filter: Optional[str] = None) -> Dict[str, Any]:
    """
    Retorna itens de um grupo já transformados em estrutura amigável para o frontend.

    - Agrupa por 'source'
    - Remove itens marcados como 'do_not_show'
    - Aplica filtro de status se fornecido
    """
    header, body = read_items_cached()
    idx: Dict[str, int] = {
        name: header.index(name) for name in ITEMS_HEADER if name in header
    }

    target_canon = _canon_group(group)
    items_raw = [
        r
        for r in body
        if r
        and _canon_group(r[idx["group"]]) == target_canon
        and (r[idx.get("do_not_show", len(r) - 1)] != "1")
    ]

    meta: Dict[str, Dict[str, Any]] = {}
    for r in items_raw:
        uid = r[idx["uid"]]
        meta[uid] = {
            "uid": uid,
            "group": r[idx["group"]],
            "source": r[idx["source"]],
            "title": r[idx["title"]],
            "link": absolutize_for_source(r[idx["link"]], r[idx["source"]]),
            "seen": r[idx["seen"]],
            "status": r[idx["status"]] or "pendente",
            "notes": r[idx["notes"]],
            "deadline_iso": r[idx["deadline_iso"]],
            "published_iso": r[idx["published_iso"]],
            "agency": r[idx["agency"]],
            "region": r[idx["region"]],
            "do_not_show": r[idx["do_not_show"]] == "1",
        }

    # Agrupa por source
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for uid, info in meta.items():
        current_status = info["status"] or "pendente"
        if current_status not in STATUS_CHOICES:
            current_status = "pendente"
        if status_filter and status_filter != "Todos":
            if current_status != status_filter:
                continue
        src = info.get("source") or "—"
        by_source.setdefault(src, []).append(info)

    # Ordena por deadline dentro de cada fonte
    for src, items in by_source.items():
        items.sort(
            key=lambda info: info.get("deadline_iso") or "9999-12-31T00:00:00"
        )

    # Constrói lista ordenada de fontes
    sources_list = []
    for src in sorted(by_source.keys(), key=lambda s: s.lower()):
        sources_list.append(
            {
                "source": src,
                "items": by_source[src],
            }
        )

    total_items = sum(len(x["items"]) for x in sources_list)

    return {
        "group": group,
        "items_count": total_items,
        "status_choices": STATUS_CHOICES,
        "sources": sources_list,
    }


def update_items(updates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aplica atualizações de campos (seen, status, notes, do_not_show)
    com base no uid dos itens.

    'updates' é lista de dicts: { uid, seen(bool), status, notes, do_not_show(bool) }.
    """
    if not updates:
        return {"updated": 0}

    header, body = read_items_cached()
    idx: Dict[str, int] = {
        name: header.index(name) for name in ITEMS_HEADER if name in header
    }
    _, _, _, ws_items, _ = open_sheet()

    uid_to_rownum: Dict[str, int] = {}
    for i, r in enumerate(body, start=2):  # linha 2 em diante
        if r and r[0]:
            uid_to_rownum[r[0]] = i

    batch: List[Tuple[str, List[List[str]]]] = []

    for u in updates:
        uid = u.get("uid")
        if not uid:
            continue
        rownum = uid_to_rownum.get(uid)
        if not rownum:
            continue

        seen_val = "1" if u.get("seen") else ""
        status_val = u.get("status") or "pendente"
        notes_val = u.get("notes") or ""
        dns_val = "1" if u.get("do_not_show") else ""

        rng_seen = f"items!{col_letter(idx['seen'])}{rownum}"
        rng_stat = f"items!{col_letter(idx['status'])}{rownum}"
        rng_notes = f"items!{col_letter(idx['notes'])}{rownum}"
        rng_dns = f"items!{col_letter(idx['do_not_show'])}{rownum}"

        batch += [
            (rng_seen, [[seen_val]]),
            (rng_stat, [[status_val]]),
            (rng_notes, [[notes_val]]),
            (rng_dns, [[dns_val]]),
        ]

    if not batch:
        return {"updated": 0}

    try:
        values_batch_update(ws_items, batch)
        invalidate_items_cache()
    except Exception as e:
        push_error("update_items", e)
        return {"updated": 0}

    return {"updated": len(updates)}


def delete_items_by_uids(uids: List[str]) -> Dict[str, Any]:
    """
    Remove da planilha os itens cujo uid esteja em 'uids'.

    A exclusão é feita linha a linha, de baixo para cima.
    """
    if not uids:
        return {"deleted": 0}

    header, body = read_items_cached()
    uid_to_rownum: Dict[str, int] = {}
    for i, r in enumerate(body, start=2):
        if r and r[0]:
            uid_to_rownum[r[0]] = i

    _, _, _, ws_items, _ = open_sheet()

    rownums = [uid_to_rownum[u] for u in uids if u in uid_to_rownum]
    rownums = sorted(set(rownums), reverse=True)

    deleted = 0
    try:
        for rn in rownums:
            ws_items.delete_rows(rn)
            deleted += 1
        invalidate_items_cache()
    except Exception as e:
        push_error("delete_items_by_uids", e)

    return {"deleted": deleted}


def clear_all_items() -> Dict[str, Any]:
    """
    Limpa a aba 'items' mantendo apenas o cabeçalho.

    Equivalente ao botão "Limpar TODOS os itens" do Streamlit.
    """
    clear_items_sheet()
    return {"cleared": True}


def get_diag_providers(re_gov: str, re_phil: str, re_latam: str) -> Dict[str, Any]:
    """
    Executa o diagnóstico dos providers, semelhante à aba "🔬 Diagnóstico".

    Retorna um dicionário com:
    - "rows": lista de linhas (grupo, fonte, itens, tempo, erro, hint)
    - "logs": últimas 200 linhas da aba 'logs'
    """
    mods = load_providers()
    cfg = read_config()

    re_map_diag: Dict[str, re.Pattern] = {}
    all_groups = {m.PROVIDER.get("group", "") for m in mods}
    for g in all_groups:
        key = _regex_key_for_group(g)
        if _canon_group(g) == _canon_group("Governo/Multilaterais"):
            pat = re_gov or DEFAULT_REGEX.get("RE_GOV", r".*")
            fb = DEFAULT_REGEX.get("RE_GOV", r".*")
        elif _canon_group(g) == _canon_group("Filantropia"):
            pat = re_phil or DEFAULT_REGEX.get("RE_PHIL", r".*")
            fb = DEFAULT_REGEX.get("RE_PHIL", r".*")
        elif _canon_group(g) == _canon_group("América Latina / Brasil"):
            pat = re_latam or DEFAULT_REGEX.get("RE_LATAM", r".*")
            fb = DEFAULT_REGEX.get("RE_LATAM", r".*")
        else:
            pat = cfg.get(key, r".*")
            fb = r".*"
        re_map_diag[g] = _compile_re(pat, fallback=fb)

    rows = []
    import time

    for mod in mods:
        g = mod.PROVIDER.get("group", "")
        key = _regex_key_for_group(g)
        rgx = re_map_diag.get(g, _compile_re(cfg.get(key, r".*"), r".*"))
        t0 = time.time()
        err = ""
        n = 0
        url_hint = getattr(mod, "URL_HINT", "")
        try:
            data = mod.fetch(rgx, cfg) or []
            n = len(data)
        except Exception as e:
            push_error(f"{mod.PROVIDER.get('name')} fetch (diag)", e)
            err = f"{type(e).__name__}: {e}"
        dt = time.time() - t0
        rows.append(
            {
                "Grupo": g,
                "Fonte": mod.PROVIDER.get("name", ""),
                "Itens": n,
                "Tempo (s)": f"{dt:.2f}",
                "Erro": err,
                "Hint": url_hint,
            }
        )

    logs = get_logs_tail(200)
    return {
        "rows": rows,
        "logs": logs,
    }
