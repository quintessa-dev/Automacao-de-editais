# -*- coding: utf-8 -*-
"""
Módulo de configuração.

Agora lê variáveis de ambiente do sistema OU do arquivo .env na raiz.
"""

import os
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env da raiz do projeto (…/backend/..)
ROOT_DIR = Path(__file__).resolve().parent.parent
env_path = ROOT_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # fallback: .env no diretório atual se quiser
    load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheet_url() -> str:
    url = os.getenv("SHEET_URL")
    if not url:
        raise RuntimeError(
            "SHEET_URL não definido. Preencha no arquivo .env na raiz do projeto."
        )
    return url


def get_google_oauth() -> Dict[str, Any]:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    token_uri = os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")

    missing = []
    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not refresh_token:
        missing.append("GOOGLE_REFRESH_TOKEN")

    if missing:
        raise RuntimeError(
            "Faltam variáveis de ambiente para Google OAuth: " + ", ".join(missing)
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "token_uri": token_uri,
    }


def get_perplexity_api_key() -> Optional[str]:
    return os.getenv("PERPLEXITY_API_KEY")
