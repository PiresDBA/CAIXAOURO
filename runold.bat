@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================
echo   🥇 AGENTE OURO CAIXA v4.0 (INTELIGENTE)
echo   Automação de Filtros + Extração Endereço
echo ==========================================
echo.

:: 1. Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [❌] Python nao encontrado!
    echo [💡] Instale em: https://python.org 
    pause & exit /b 1
)
echo [✅] Python detectado.

:: 2. Cria/ativa venv
if not exist venv (
    echo [1/5] Criando ambiente virtual...
    python -m venv venv
)
call venv\Scripts\activate.bat

:: 3. Instala dependências básicas
echo [2/5] Instalando pacotes base...
pip install --upgrade pip -q
pip install -q streamlit requests pdfplumber pillow beautifulsoup4

:: 4. Playwright (CRÍTICO)
echo [3/5] Configurando Playwright (Isso pode demorar)...
pip install -q playwright

:: Instala o navegador
playwright install chromium

:: INSTALA AS DEPENDÊNCIAS DO SISTEMA (FFMPEG, DLLs, etc) - ESSENCIAL NO WINDOWS
echo [!] Instalando dependências do sistema Windows...
playwright install-deps chromium
if errorlevel 1 (
    echo [⚠️] Aviso: install-deps pode exigir permissao de Administrador.
    echo [💡] Se falhar, clique com botão direito no run.bat e escolha "Executar como Administrador".
)

:: 5. Tesseract OCR
where tesseract >nul 2>&1
if errorlevel 1 (
    echo [⚠️] Tesseract OCR nao encontrado. OCR automatico desativado.
    echo [💡] Para ativar: winget install UB-Mannheim.TesseractOCR
)

:: 6. Executa
echo [4/5] Iniciando interface web...
echo.
echo   🔗 Acesse: http://localhost:8501
echo   🤖 Modo: Filtro Automático UF=SP + Mês Atual
echo   🛑 Para encerrar: Ctrl+C nesta janela
echo.
echo ==========================================

set PYTHONASYNCIODEBUG=0
streamlit run app.py --server.port 8501 --server.enableCORS false --server.enableXsrfProtection false

echo.
echo [✅] Aplicacao encerrada.
pause