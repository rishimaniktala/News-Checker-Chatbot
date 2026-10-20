"""Prompt loading must never read outside prompt_files. PROMPT_VERSION comes from the environment."""

import subprocess
import sys
from pathlib import Path

import pytest

from app import prompts

BACKEND = Path(__file__).resolve().parents[1]
BAD_VERSIONS = [
    "../x", "../../etc/passwd", "/etc/passwd", "v2/../v1", "v2/", "..\\..", "v2\n", "v2\x00", " v2",
    "ｖ２", "v２", "%2e%2e", "~", "v2;ls", "v2 ", "C:\\x", "\u202ev2",
]


@pytest.mark.parametrize("version", BAD_VERSIONS)
def test_load_prompt_rejects_hostile_versions(version):
    with pytest.raises(ValueError):
        prompts.load_prompt("extraction", version)


def test_empty_version_falls_back_to_the_default_set():
    assert prompts.load_prompt("extraction", "") == prompts.load_prompt("extraction", prompts.PROMPT_VERSION)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_known_versions_load_every_prompt(version):
    for name in ("extraction", "ocr", "verdict", "evidence_check", "review"):
        assert prompts.load_prompt(name, version).strip()


def test_unknown_but_well_formed_version_fails_with_file_not_found():
    with pytest.raises(FileNotFoundError):
        prompts.load_prompt("extraction", "v99")


def test_every_shipped_prompt_resolves_inside_prompt_files():
    root = prompts.PROMPT_DIR.resolve()
    for f in root.rglob("*"):
        assert f.resolve().is_relative_to(root), f


@pytest.mark.parametrize("version", ["..", "."])
def test_dot_versions_cannot_escape_the_prompt_dir(version, tmp_path, monkeypatch):
    root = tmp_path / "prompt_files"
    (root / "v2").mkdir(parents=True)
    (tmp_path / "extraction.md").write_text("OUTSIDE-SECRET")
    (root / "extraction.md").write_text("OUTSIDE-SECRET")
    monkeypatch.setattr(prompts, "PROMPT_DIR", root)
    with pytest.raises(ValueError):
        prompts.load_prompt("extraction", version)


@pytest.mark.xfail(strict=True, reason="SEC-2: the prompt name is not validated; '../..' in it escapes (name is code-controlled today)")
def test_prompt_name_cannot_traverse(tmp_path, monkeypatch):
    root = tmp_path / "prompt_files"
    (root / "v2").mkdir(parents=True)
    (tmp_path / "secret.md").write_text("OUTSIDE-SECRET")
    monkeypatch.setattr(prompts, "PROMPT_DIR", root)
    with pytest.raises(ValueError):
        prompts.load_prompt("../../secret", "v2")


def import_with(version: str) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "PROMPT_VERSION": version, "NEWS_DB": ":memory:"}
    return subprocess.run([sys.executable, "-c", "import app.prompts as p; print(p.PROMPT_VERSION)"],
                          cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("version", ["../../etc", "/etc/passwd", "v2/../v1", "ｖ２"])
def test_env_prompt_version_with_traversal_stops_the_import(version):
    r = import_with(version)
    assert r.returncode != 0 and "bad prompt version" in r.stderr


def test_env_prompt_version_v1_and_blank_import_cleanly():
    assert import_with("v1").stdout.strip() == "v1"
    assert import_with("   ").stdout.strip() == "v2"
