import pytest

KEYS = ("GEMINI_API_KEY", "GUARDIAN_API_KEY", "FACTCHECK_API_KEY", "FIRECRAWL_API_KEY")


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    """The real .env is loaded at import; no test may reach a live API unless it sets a key itself."""
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_guardian_throttle(monkeypatch):
    monkeypatch.setattr("app.retrievers.guardian.MIN_GAP_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def isolated_server_state(monkeypatch, tmp_path):
    """Own database per test, rate limit off, empty limiter and run counter."""
    from app import main

    monkeypatch.setenv("NEWS_DB", str(tmp_path / "default.db"))
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")
    monkeypatch.delenv("RUNS_TOKEN", raising=False)
    monkeypatch.setattr(main, "_buckets", {})
    monkeypatch.setattr(main, "_active_runs", 0)
