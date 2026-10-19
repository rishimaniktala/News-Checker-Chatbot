import base64
import json

import httpx
import pytest

import app.inputs as inputs
from app.inputs import InputError, normalize_image, normalize_url
from app.schemas import OcrResult

PUBLIC = lambda host: ["93.184.216.34"]
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
b64 = lambda b: base64.b64encode(b).decode()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(inputs, "call_with_retry", lambda fn, api, retries=2: fn())


def fc(body, status=200):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler), calls


def ok(markdown, **meta):
    return {"success": True, "data": {"markdown": markdown, "metadata": meta}}


def fetch(body, status=200):
    t, calls = fc(body, status)
    return normalize_url("https://example.com/a", transport=t, resolver=PUBLIC), calls


def code(body, status=200, url="https://example.com/a"):
    t, _ = fc(body, status)
    with pytest.raises(InputError) as e:
        normalize_url(url, transport=t, resolver=PUBLIC)
    return e.value.code


def test_fetch_goes_only_to_firecrawl():
    out, calls = fetch(ok("Hello", statusCode=200))
    assert out.text == "Hello" and out.source_url == "https://example.com/a"
    assert [str(c.url) for c in calls] == [inputs.FIRECRAWL_URL]
    assert json.loads(calls[0].content)["url"] == "https://example.com/a"


def test_unsafe_url_never_fetched():
    t, calls = fc(ok("x"))
    with pytest.raises(InputError) as e:
        normalize_url("http://127.0.0.1", transport=t, resolver=PUBLIC)
    assert e.value.code == "unsafe_url" and calls == []


def test_truncates_at_20000():
    out, _ = fetch(ok("a" * 30000, statusCode=200))
    assert len(out.text) == 20000


@pytest.mark.parametrize("body,status", [
    (ok("x", statusCode=403), 200),
    (ok("x", statusCode=404), 200),
    (ok("x", contentType="application/pdf"), 200),
    (ok("   ", statusCode=200), 200),
    ({"success": False}, 200),
    ({}, 500),
    ({}, 402),
])
def test_fetch_failures(body, status):
    assert code(body, status) == "fetch_failed"


def test_pdf_by_extension():
    assert code(ok("x"), url="https://example.com/a.pdf") == "fetch_failed"


def test_oversized_response():
    assert code(ok("a" * 3_000_000)) == "fetch_failed"


def test_missing_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY")
    assert code(ok("x")) == "fetch_failed"


def ocr_ok(raw, mime):
    return OcrResult(text="Breaking news", context_note="meme", is_legible=True)


def test_image_ok():
    out = normalize_image(b64(PNG), "image/png", ocr=ocr_ok)
    assert out.text == "Breaking news" and out.input_type == "image"


@pytest.mark.parametrize("data,mime", [
    (b64(PNG), "image/gif"),
    (b64(b"\xff\xd8\xff" + b"0" * 9), "image/png"),
    (b64(PNG), "image/jpeg"),
    ("not base64!!", "image/png"),
    (b64(PNG + b"0" * (5 * 1024 * 1024)), "image/png"),
    ("", "image/png"),
])
def test_bad_images(data, mime):
    with pytest.raises(InputError) as e:
        normalize_image(data, mime, ocr=ocr_ok)
    assert e.value.code == "bad_input"


@pytest.mark.parametrize("res", [
    OcrResult(text="x", context_note="", is_legible=False),
    OcrResult(text="  ", context_note="", is_legible=True),
])
def test_illegible_ocr(res):
    with pytest.raises(InputError) as e:
        normalize_image(b64(PNG), "image/png", ocr=lambda r, m: res)
    assert e.value.code == "unreadable_image"
    assert "sharper screenshot" in e.value.message
