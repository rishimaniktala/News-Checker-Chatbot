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
