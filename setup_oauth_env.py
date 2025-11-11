# -*- coding: utf-8 -*-
"""
Gera refresh_token via OAuth Desktop (loopback localhost) e cria/atualiza .env.

Requisitos:
  pip install google-auth google-auth-oauthlib google-api-python-client python-dotenv
"""

from pathlib import Path
from typing import Optional
import json

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def ask(prompt: str, default: Optional[str] = None) -> str:
    """
    Pergunta simples no terminal com valor padrão.
    """
    s = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return s or (default or "")


def main():
    root = Path(__file__).resolve().parent

    # 1) Arquivo client_secret.json (OAuth Desktop) na raiz do projeto
    client_json = root / "client_secret.json"
    if not client_json.exists():
        raise FileNotFoundError(
            f"Não achei {client_json}. "
            "Coloque aqui o client_secret.json (tipo 'Desktop app')."
        )

    # 2) Dados para .env
    print("\n== Dados para o .env ==")
    sheet_url = ask("Cole a URL da sua planilha Google (SHEET_URL)")
    pplx_key = ask(
        "Perplexity API key (opcional, ENTER para pular)", ""
    )

    # 3) Fluxo OAuth Desktop (loopback)
    print("\nAbrirei o navegador para autorizar o acesso (Sheets/Drive).")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_json), SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=8080,          # troque se estiver ocupado
        prompt="consent",   # garante refresh_token novo
        access_type="offline",
    )
    if not creds.valid:
        creds.refresh(Request())

    refresh_token = creds.refresh_token
    if not refresh_token:
        raise RuntimeError(
            "Não recebi refresh_token. "
            "Revogue acessos antigos na sua Conta Google e rode de novo."
        )

    # 4) Lê client_id/client_secret do client_secret.json
    cfg = json.loads(client_json.read_text(encoding="utf-8"))
    client_info = cfg["installed"]
    client_id = client_info["client_id"]
    client_secret = client_info["client_secret"]
    token_uri = client_info.get("token_uri", "https://oauth2.googleapis.com/token")

    # 5) Monta .env e salva na raiz (faz backup se já existir)
    env_path = root / ".env"

    if env_path.exists():
        backup = root / ".env.backup"
        env_path.replace(backup)
        print(f"⚠️  {env_path} já existia — fiz backup em: {backup}")

    lines = []

    def set_var(k: str, v: str) -> None:
        # salva sempre em aspas para evitar problemas com caracteres especiais
        v = v.replace('"', '\\"')
        lines.append(f'{k}="{v}"')

    set_var("SHEET_URL", sheet_url)
    set_var("GOOGLE_CLIENT_ID", client_id)
    set_var("GOOGLE_CLIENT_SECRET", client_secret)
    set_var("GOOGLE_REFRESH_TOKEN", refresh_token)
    set_var("GOOGLE_TOKEN_URI", token_uri)

    if pplx_key:
        set_var("PERPLEXITY_API_KEY", pplx_key)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 6) Também deixo um token.json, se quiser reutilizar depois
    (root / "token.json").write_text(creds.to_json(), encoding="utf-8")

    print("\n✅ Pronto!")
    print(f"- Refresh token obtido e salvo.")
    print(f"- .env gravado em: {env_path}")
    print(f"- token.json gravado em: {root / 'token.json'}")
    print("\nDa próxima vez, é só dar dois cliques no .bat que ele já usa esse .env.")


if __name__ == "__main__":
    main()
