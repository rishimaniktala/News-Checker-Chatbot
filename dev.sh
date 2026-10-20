#!/usr/bin/env bash
# Start backend (:8000) and frontend (:3000). Ctrl-C stops both.
set -e
cd "$(dirname "$0")"
[ -x backend/.venv/bin/python ] || { echo "No backend venv. Run: python3.12 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.lock"; exit 1; }
[ -d frontend/node_modules ] || { echo "No frontend/node_modules. Run: cd frontend && npm ci"; exit 1; }
[ -f .env ] || echo "Note: no .env found. Copy .env.example to .env and add keys."
trap 'kill 0' EXIT
(cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000) &
(cd frontend && NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev) &
wait
