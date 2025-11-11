@echo off
setlocal

REM Caminho da pasta do projeto (esta linha usa a pasta onde o .bat está)
set PROJECT_DIR=%~dp0

cd /d "%PROJECT_DIR%"

REM 1) Cria venv se não existir
if not exist venv (
    echo [SETUP] Criando ambiente virtual...
    python -m venv venv
)

REM 2) Ativa venv
call "%PROJECT_DIR%venv\Scripts\activate.bat"

REM 3) Instala dependencias
echo [SETUP] Instalando dependencias (pode demorar um pouco)...
pip install --upgrade pip
pip install fastapi uvicorn gspread google-auth google-auth-oauthlib ^
 requests feedparser beautifulsoup4 dateparser pytz python-dateutil pandas ^
 python-dotenv google-api-python-client

REM 4) Se nao tiver .env ainda, roda o script de setup de credenciais
if not exist ".env" (
    echo [SETUP] Arquivo .env nao encontrado. Rodando setup de credenciais...
    python setup_oauth_env.py
)

REM 5) Sobe o servidor FastAPI
echo [RUN] Iniciando servidor em http://localhost:8000 ...
uvicorn backend.api:app --host 0.0.0.0 --port 8000

echo.
echo [INFO] Servidor foi finalizado.
pause
