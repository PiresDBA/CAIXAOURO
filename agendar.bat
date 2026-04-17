@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -c "from app import run_pipeline; run_pipeline()"