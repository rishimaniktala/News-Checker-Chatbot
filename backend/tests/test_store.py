from app import store


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "t.db"))
    store.save_run("r1", {"kind": "text", "text": "hi"}, [{"type": "done"}], {"answer": "a"}, 0.01, 12)
    run = store.load_run("r1")
    assert run["request"]["text"] == "hi"
    assert run["events"] == [{"type": "done"}]
    assert run["cost_usd"] == 0.01


def test_missing_run_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "t.db"))
    assert store.load_run("nope") is None


def test_image_bytes_are_not_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "t.db"))
    store.save_run("r1", {"kind": "image", "image_b64": "AAAA"}, [], None, 0, 1)
    assert "AAAA" not in str(store.load_run("r1"))


def test_purge_removes_only_old_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "t.db"))
    store.save_run("old", {}, [], None, 0, 1)
    store.save_run("new", {}, [], None, 0, 1)
    with store._connect() as db:
        db.execute("UPDATE runs SET created = datetime('now', '-40 days') WHERE run_id = 'old'")
    assert store.purge_older_than(30) == 1
    assert store.load_run("old") is None and store.load_run("new") is not None


def test_startup_runs_the_purge(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("RUNS_RETENTION_DAYS", "1")
    store.save_run("old", {}, [], None, 0, 1)
    with store._connect() as db:
        db.execute("UPDATE runs SET created = datetime('now', '-3 days')")
    with TestClient(main.app):
        pass
    assert store.load_run("old") is None


def test_check_writable_fails_on_bad_path(monkeypatch):
    import pytest
    monkeypatch.setenv("NEWS_DB", "/nonexistent-dir/x.db")
    with pytest.raises(Exception):
        store.check_writable()
