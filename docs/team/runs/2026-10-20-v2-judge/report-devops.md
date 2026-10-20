# Report: devops
DONE: ci.yml (backend, frontend, eval-smoke, secrets), dependabot, gitleaks config, Dockerfiles and compose (localhost-bound, non-root, single worker), Makefile, dev.sh checks, .env.example (20 vars), docs/ops.md, requirements.lock (37 pins), ruff.toml.
EVIDENCE (engineer's claim, lead to re-run): toml parse ok; bash -n dev.sh ok; eval --fake ran; pytest 431 passed, 2 skipped. YAML checked by eye only.
FINDINGS: config.py lacks the new env vars (belongs to backend); frontend has no output standalone; CI installs ruff outside the lock so first run may fail lint; lock includes test deps.
GAPS: docker not built, ruff not run, workflows unverified until first push.
BLOCKERS: none
