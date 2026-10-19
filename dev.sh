#!/usr/bin/env bash
# Start backend (:8000) and frontend (:3000). Ctrl-C stops both.
set -e
cd "$(dirname "$0")"
trap 'kill 0' EXIT
(cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000) &
(cd frontend && NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev) &
wait
