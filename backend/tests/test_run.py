import app.llm as llm
import sys
import types

import pytest

from app import orchestrator, run
from app.schemas import InputType, NormalizedInput
from test_orchestrator import SETTINGS, make_budget, make_claim, search
from app.schemas import ClaimExtraction


class FakeInputError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@pytest.fixture
def fake_inputs(monkeypatch):
    mod = types.ModuleType("app.inputs")
    mod.InputError = FakeInputError
    mod.normalize_url = lambda url: NormalizedInput(input_type=InputType.URL, text="article", source_url=url)

    def normalize_image(b64, mime):
        raise FakeInputError("unreadable_image", "I could not read that image.")

    mod.normalize_image = normalize_image
    monkeypatch.setitem(sys.modules, "app.inputs", mod)
    import app
    monkeypatch.setattr(app, "inputs", mod, raising=False)
    return mod


@pytest.fixture
def seen_text(monkeypatch):
    seen = []

    def extract(inp):
        seen.append(inp)
        return ClaimExtraction(claims=[], notes="nothing")

    monkeypatch.setattr(orchestrator, "extract_claims", extract)
    return seen


def go(req):
    events = []
    report = run.run_check(req, events.append, SETTINGS, search, make_budget())
    return report, events


def test_text_run_emits_normalize_then_extract(seen_text, fake_inputs):
    report, events = go({"kind": "text", "text": "hello", "run_id": "abc"})
    assert [e["step"] for e in events][:2] == ["normalize", "normalize"]
    assert report.run_id == "abc"
    assert seen_text[0].text == "hello"


def test_long_text_is_cut_with_a_trace_note(seen_text, fake_inputs):
    _, events = go({"kind": "text", "text": "a" * (run.MAX_TEXT_CHARS + 5)})
    assert len(seen_text[0].text) == run.MAX_TEXT_CHARS
    assert any("cut" in e["message"] for e in events)


def test_url_goes_through_normalize_url(seen_text, fake_inputs):
    go({"kind": "url", "url": "https://a.test/x"})
    assert seen_text[0].source_url == "https://a.test/x"


@pytest.mark.parametrize("req", [{"kind": "text", "text": "  "}, {"kind": "video"}, {}])
def test_bad_requests_raise_bad_input(req, fake_inputs):
    with pytest.raises(run.RunInputError) as e:
        go(req)
    assert e.value.code == "bad_input"


def test_oversize_image_is_rejected(fake_inputs):
    big = "A" * (run.MAX_IMAGE_BYTES * 4 // 3 + 10)
    with pytest.raises(run.RunInputError) as e:
        go({"kind": "image", "image_b64": big, "mime": "image/png"})
    assert e.value.code == "bad_input"


def test_input_error_from_inputs_keeps_its_code(fake_inputs):
    with pytest.raises(run.RunInputError) as e:
        go({"kind": "image", "image_b64": "AAAA", "mime": "image/png"})
    assert e.value.code == "unreadable_image"


def test_usage_reaches_budget(monkeypatch, seen_text, fake_inputs):
    from app import agents
    budget = make_budget()

    def extract(inp):
        llm._usage_sink.get()("m", 10, 5)
        return ClaimExtraction(claims=[])

    monkeypatch.setattr(orchestrator, "extract_claims", extract)
    run.run_check({"kind": "text", "text": "x"}, lambda e: None, SETTINGS, search, budget)
    assert (budget.tokens_in, budget.tokens_out) == (10, 5)
