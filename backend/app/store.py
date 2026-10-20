"""SQLite store for finished runs and the report cache. One JSON document per row.

One process assumed: SQLite handles concurrent writers, but nothing else is shared."""

import json
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "runs.db"


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(os.environ.get("NEWS_DB") or DEFAULT_DB)
    db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, data TEXT NOT NULL, "
               "cost_usd REAL, latency_ms INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    db.execute("CREATE TABLE IF NOT EXISTS report_cache (key TEXT PRIMARY KEY, report TEXT NOT NULL, "
               "created TEXT DEFAULT CURRENT_TIMESTAMP)")
    return db


def save_run(run_id: str, request: dict, events: list[dict], report: dict | None,
             cost_usd: float, latency_ms: int, calls: list[dict] | None = None) -> None:
    request = {k: ("<omitted>" if k == "image_b64" else v) for k, v in request.items()}
    data = json.dumps({"run_id": run_id, "request": request, "events": events, "report": report,
                       "cost_usd": cost_usd, "latency_ms": latency_ms, "calls": calls or []})
    with _connect() as db:
        db.execute("INSERT OR REPLACE INTO runs (run_id, data, cost_usd, latency_ms) VALUES (?, ?, ?, ?)",
                   (run_id, data, cost_usd, latency_ms))


def load_run(run_id: str) -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT data FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_get(key: str, ttl_hours: float) -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT report FROM report_cache WHERE key = ? AND created > datetime('now', ?)",
                         (key, f"-{ttl_hours} hours")).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(key: str, report: dict) -> None:
    with _connect() as db:
        db.execute("INSERT OR REPLACE INTO report_cache (key, report, created) VALUES (?, ?, CURRENT_TIMESTAMP)",
                   (key, json.dumps(report)))


def purge_older_than(days: float) -> int:
    """Delete runs and cache rows older than `days`. Returns the number of runs removed."""
    cutoff = f"-{days} days"
    with _connect() as db:
        db.execute("DELETE FROM report_cache WHERE created < datetime('now', ?)", (cutoff,))
        return db.execute("DELETE FROM runs WHERE created < datetime('now', ?)", (cutoff,)).rowcount


def check_writable() -> None:
    """Raise if the database cannot take a write."""
    db = _connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.rollback()
    finally:
        db.close()
