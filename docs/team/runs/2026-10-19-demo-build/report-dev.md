# Report: dev
DONE: url_safety.check_url (scheme, port, userinfo, localhost, numeric IP encodings, all-address DNS check, IPv4-mapped IPv6), inputs.normalize_url (Firecrawl only, 20000-char cap), normalize_image (mime, 5 MB, base64, magic bytes, legibility).
FILES: backend/app/url_safety.py, backend/app/inputs.py, backend/tests/test_url_safety.py, backend/tests/test_inputs.py
EVIDENCE (dev's claim, lead to re-run): `cd backend && .venv/bin/python -m pytest -q` -> 73 passed (whole suite at that time).
FINDINGS: tests monkeypatch call_with_retry because resilience was still a stub; assumes callable raises httpx.HTTPStatusError on 429/5xx; Firecrawl v1 response shape unverified live.
GAPS: no DNS pinning (Firecrawl fetches, rebinding window remains); default OCR path untested; injection handling left to prompts.
BLOCKERS: none
