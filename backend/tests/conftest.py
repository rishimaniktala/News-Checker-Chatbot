import pytest

KEYS = ("GEMINI_API_KEY", "GUARDIAN_API_KEY", "FACTCHECK_API_KEY", "FIRECRAWL_API_KEY")


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    """The real .env is loaded at import; no test may reach a live API unless it sets a key itself."""
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
