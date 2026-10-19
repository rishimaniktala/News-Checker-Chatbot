"""SQLite store for finished runs. One JSON document per run."""

import json
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "runs.db"


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(os.environ.get("NEWS_DB") or DEFAULT_DB)
    db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, data TEXT NOT NULL, "
               "cost_usd REAL, latency_ms INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    return db


def save_run(run_id: str, request: dict, events: list[dict], report: dict | None,
             cost_usd: float, latency_ms: int) -> None:
    request = {k: ("<omitted>" if k == "image_b64" else v) for k, v in request.items()}
    data = json.dumps({"run_id": run_id, "request": request, "events": events, "report": report,
                       "cost_usd": cost_usd, "latency_ms": latency_ms})
    with _connect() as db:
        db.execute("INSERT OR REPLACE INTO runs (run_id, data, cost_usd, latency_ms) VALUES (?, ?, ?, ?)",
                   (run_id, data, cost_usd, latency_ms))


def load_run(run_id: str) -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT data FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None
