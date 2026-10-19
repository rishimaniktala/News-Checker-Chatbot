import os

from app.config import load_env_file


def test_env_file_fills_missing_but_never_overrides(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# c\nNEW_KEY_X="abc"\nEXISTING_Y=fromfile\nEMPTY\n')
    monkeypatch.delenv("NEW_KEY_X", raising=False)
    monkeypatch.setenv("EXISTING_Y", "fromenv")
    load_env_file(f)
    assert os.environ["NEW_KEY_X"] == "abc"
    assert os.environ["EXISTING_Y"] == "fromenv"
    monkeypatch.delenv("NEW_KEY_X", raising=False)


def test_missing_env_file_is_fine(tmp_path):
    load_env_file(tmp_path / "nope")
