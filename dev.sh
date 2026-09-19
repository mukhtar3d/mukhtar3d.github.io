#!/usr/bin/env bash
# Runs the Django API and the Vite dev server together.
# Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  echo "First run: setting up the Python environment…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
  backend/.venv/bin/python backend/manage.py migrate
  backend/.venv/bin/python backend/manage.py seed_universities
fi

if [ ! -d frontend/node_modules ]; then
  echo "First run: installing frontend packages…"
  (cd frontend && npm install)
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd backend && .venv/bin/python manage.py runserver 127.0.0.1:8000) &
(cd frontend && npm run dev) &

echo ""
echo "  API      http://127.0.0.1:8000/api/health"
echo "  App      http://localhost:5173"
echo ""
wait
