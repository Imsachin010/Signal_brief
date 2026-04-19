@echo off
echo =============================================
echo  SignalBrief - Backend (FastAPI)
echo  http://127.0.0.1:8000
echo =============================================
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
