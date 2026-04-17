@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================
echo   🥇 AGENTE OURO CAIXA v8.1 (DASHBOARD)
echo   Analise Completa + Power BI Style
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

:: 3. Instala dependências básicas e avançadas
echo [2/5] Instalando pacotes (isso pode demorar)...
pip install --upgrade pip -q
pip install -q streamlit requests pdfplumber pillow beautifulsoup4 pandas openpyxl plotly

:: 4. Playwright
echo [3/5] Configurando Playwright...
pip install -q playwright
playwright install chromium
:: Tenta instalar deps do sistema (pode falhar sem admin, mas ignora erro)
playwright install-deps chromium 2>nul

:: 5. Tesseract OCR (opcional)
where tesseract >nul 2>&1
if errorlevel 1 (
    echo [⚠️] Tesseract OCR nao encontrado. OCR automatico desativado.
    echo [💡] Para ativar: winget install UB-Mannheim.TesseractOCR
)

:: 6. Executa
echo [4/5] Iniciando interface web...
echo.
echo   🔗 Acesse: http://localhost:8501
echo   📊 Dashboard: Aba "Analise Executiva"
echo   📝 Planilha Mestra: Gerada em /data/resultados
echo   🛑 Para encerrar: Ctrl+C nesta janela
echo.
echo ==========================================

set PYTHONASYNCIODEBUG=0
streamlit run app.py --server.port 8501 --server.enableCORS false --server.enableXsrfProtection false

echo.
echo [✅] Aplicacao encerrada.
pause