"""Model routing: primary first, one fallback attempt on outages, never on auth or bad requests."""

from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from app import llm, resilience
from app.config import DEFAULT_FALLBACK, DEFAULT_PRIMARY, load_settings

GOOD = '{"x": 1}'


class Out(BaseModel):
    x: int


class ApiError(Exception):
    def __init__(self, code, msg="boom"):
        super().__init__(msg)
        self.code = code


class Fake:
    """script maps model name to a list of results; an Exception is raised, a str is the reply text."""

    def __init__(self, script):
        self.script, self.models, self.seen = script, self, []

    def generate_content(self, model, contents, config):
        self.seen.append((model, config))
        item = self.script[model].pop(0) if len(self.script[model]) > 1 else self.script[model][0]
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item, usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=2, thoughts_token_count=3))


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("MODEL_PRIMARY", "P")
    monkeypatch.setenv("MODEL_FALLBACK", "F")
    monkeypatch.setitem(resilience.call_with_retry.__kwdefaults__, "sleep", lambda s: None)
    resilience.reset_breakers()
    yield
    resilience.reset_breakers()


def route(monkeypatch, script):
    fake = Fake(script)
    monkeypatch.setattr(llm, "_get_client", lambda: fake)
    log = llm.begin_run()
    return fake, log


def call(role="judge"):
    return llm.generate("sys", "hi", Out, role=role)


def test_primary_works_no_fallback(monkeypatch):
    fake, log = route(monkeypatch, {"P": [GOOD], "F": [GOOD]})
    assert call().x == 1
    assert [m for m, _ in fake.seen] == ["P"]
    assert not log.fallback_used and log.models_used == ["P"]
    assert (log.calls[0].tokens_in, log.calls[0].tokens_out) == (10, 5)


@pytest.mark.parametrize("failure", [
    ApiError(429), ApiError(503), httpx.ReadTimeout("t"), ConnectionError("c"), ApiError(404)])
def test_outage_falls_back_once(monkeypatch, failure):
    fake, log = route(monkeypatch, {"P": [failure], "F": [GOOD]})
    assert call().x == 1
    assert fake.seen[-1][0] == "F"
    assert log.calls[-1].fallback_used and log.calls[-1].model == "F"


def test_open_circuit_falls_back_without_calling_primary(monkeypatch):
    fake, _ = route(monkeypatch, {"P": [ApiError(503)], "F": [GOOD]})
    for _ in range(3):
        call()
    primary_calls = sum(m == "P" for m, _ in fake.seen)
    call()
    assert sum(m == "P" for m, _ in fake.seen) == primary_calls


def test_breakers_are_per_model(monkeypatch):
    route(monkeypatch, {"P": [ApiError(503)], "F": [GOOD]})
    for _ in range(3):
        call()
    assert resilience._breakers["gemini:primary"][0] >= 3
    assert "gemini:fallback" not in resilience._breakers


def test_malformed_json_twice_falls_back(monkeypatch):
    fake, log = route(monkeypatch, {"P": ["nope"], "F": [GOOD]})
    assert call().x == 1
    assert [m for m, _ in fake.seen] == ["P", "P", "F"]
    assert log.fallback_used


def test_malformed_once_stays_on_primary(monkeypatch):
    fake, _ = route(monkeypatch, {"P": ["nope", GOOD], "F": [GOOD]})
    call()
    assert [m for m, _ in fake.seen] == ["P", "P"]


@pytest.mark.parametrize("code", [400, 401, 403])
def test_auth_and_bad_request_do_not_fall_back(monkeypatch, code):
    fake, _ = route(monkeypatch, {"P": [ApiError(code, "bad request")], "F": [GOOD]})
    with pytest.raises(ApiError):
        call()
    assert [m for m, _ in fake.seen] == ["P"]


def test_fallback_gets_a_single_attempt(monkeypatch):
    fake, _ = route(monkeypatch, {"P": [ApiError(503)], "F": ["nope"]})
    with pytest.raises(llm.AgentError):
        call()
    assert [m for m, _ in fake.seen].count("F") == 1


def test_same_model_for_both_slots_does_not_retry_itself(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "P")
    fake, _ = route(monkeypatch, {"P": [ApiError(503)]})
    with pytest.raises(ApiError):
        call()
    assert {m for m, _ in fake.seen} == {"P"}


def test_usage_sink_sees_the_model_that_answered(monkeypatch):
    route(monkeypatch, {"P": [ApiError(503)], "F": [GOOD]})
    seen = []
    llm.set_usage_sink(lambda m, i, o: seen.append((m, i, o)))
    try:
        call()
    finally:
        llm.set_usage_sink(None)
    assert seen == [("F", 10, 5)]


def test_rejected_thinking_config_degrades_to_none(monkeypatch):
    fake, _ = route(monkeypatch, {"P": [ApiError(400, "Thinking level is not supported"), GOOD]})
    assert call().x == 1
    assert fake.seen[0][1].thinking_config is not None and fake.seen[1][1].thinking_config is None


@pytest.mark.parametrize("role, level", [("ocr", "LOW"), ("extract", "LOW"), ("evidence", "LOW"),
                                         ("judge", "MEDIUM"), ("review", "HIGH")])
def test_thinking_level_per_role(role, level):
    assert llm._thinking_config("gemini-3.6-flash", role).thinking_level.value == level


def test_thinking_budget_for_gemini_25():
    assert llm._thinking_config("gemini-2.5-flash", "review").thinking_budget > \
        llm._thinking_config("gemini-2.5-flash", "ocr").thinking_budget


def test_embed_is_logged(monkeypatch):
    client = SimpleNamespace(models=SimpleNamespace(
        embed_content=lambda model, contents: SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1])])))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    log = llm.begin_run()
    assert llm.embed(["a"]) == [[0.1]]
    assert log.last("embed").model == llm.EMBED_MODEL


def test_defaults_and_alias(monkeypatch):
    for n in ("MODEL_PRIMARY", "MODEL_FALLBACK", "GEMINI_MODEL"):
        monkeypatch.delenv(n, raising=False)
    s = load_settings()
    assert (s.model_primary, s.model_fallback) == (DEFAULT_PRIMARY, DEFAULT_FALLBACK)
    monkeypatch.setenv("GEMINI_MODEL", "legacy")
    assert load_settings().model_primary == "legacy" == load_settings().gemini_model


def test_models_used_leaves_out_the_embedding_model():
    from app.llm import CallRecord, RunLog

    log = RunLog(calls=[CallRecord("judge", "gemini-3.6-flash"), CallRecord("embed", "gemini-embedding-001")])
    assert log.models_used == ["gemini-3.6-flash"]
