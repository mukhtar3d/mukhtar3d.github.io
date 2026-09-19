@echo off
REM Windows equivalent of dev.sh — opens two windows.
start "UniPath API" cmd /k "cd backend && .venv\Scripts\python manage.py runserver 127.0.0.1:8000"
start "UniPath App" cmd /k "cd frontend && npm run dev"
echo API  http://127.0.0.1:8000/api/health
echo App  http://localhost:5173
