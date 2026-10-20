PY := backend/.venv/bin/python

.PHONY: dev test lint eval-fake docker-up

dev:
	./dev.sh

test:
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npm test

lint:
	cd backend && .venv/bin/python -m ruff check .
	cd frontend && npm run lint

eval-fake:
	$(PY) eval/run_eval.py --fake --claims eval/claims.json --configs eval/configs.json --out eval/results/fake

docker-up:
	docker compose up --build
