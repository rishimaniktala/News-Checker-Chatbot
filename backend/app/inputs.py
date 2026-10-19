"""Turn a URL or an uploaded image into a NormalizedInput. Both are untrusted."""

import base64
import binascii
import os
from typing import Callable

import httpx

from app.resilience import CircuitOpen, call_with_retry
from app.schemas import InputType, NormalizedInput
from app.url_safety import UnsafeUrl, check_url

FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"
FETCH_TIMEOUT_S = 20
MAX_TEXT_CHARS = 20000
MAX_RESPONSE_BYTES = 2_000_000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}

FETCH_FAILED = "I couldn't read that page. Paste the article text instead."


class InputError(Exception):
    """code is one of bad_input, unsafe_url, fetch_failed, unreadable_image."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _scrape(url: str, transport: httpx.BaseTransport | None) -> dict:
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        raise InputError("fetch_failed", FETCH_FAILED)

    def call() -> httpx.Response:
        with httpx.Client(transport=transport, timeout=FETCH_TIMEOUT_S) as client:
            r = client.post(
                FIRECRAWL_URL,
                json={"url": url, "formats": ["markdown"]},
                headers={"Authorization": f"Bearer {key}"},
            )
        if r.status_code == 429 or r.status_code >= 500:
            r.raise_for_status()
        return r

    try:
        r = call_with_retry(call, api="firecrawl")
    except (httpx.HTTPError, CircuitOpen):
        raise InputError("fetch_failed", FETCH_FAILED)
    if r.status_code != 200 or len(r.content) > MAX_RESPONSE_BYTES:
        raise InputError("fetch_failed", FETCH_FAILED)
    try:
        return r.json()
    except ValueError:
        raise InputError("fetch_failed", FETCH_FAILED)


def normalize_url(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
    resolver: Callable[[str], list[str]] | None = None,
) -> NormalizedInput:
    try:
        safe = check_url(url, resolver) if resolver else check_url(url)
    except UnsafeUrl as e:
        raise InputError("unsafe_url", e.message)

    body = _scrape(safe, transport)
    data = body.get("data") if isinstance(body, dict) and body.get("success") else None
    if not isinstance(data, dict):
        raise InputError("fetch_failed", FETCH_FAILED)
    meta = data.get("metadata") or {}
    status = meta.get("statusCode", 200)
    if status in (401, 402, 403):
        raise InputError("fetch_failed", "That page is behind a paywall or login. Paste the article text instead.")
    if status == 404:
        raise InputError("fetch_failed", "That page doesn't exist any more (404). Check the link.")
    if "pdf" in str(meta.get("contentType", "")).lower() or safe.lower().split("?")[0].endswith(".pdf"):
        raise InputError("fetch_failed", "That link is a PDF, which I can't read yet. Paste the text instead.")
    text = (data.get("markdown") or "").strip()
    if status >= 400 or not text:
        raise InputError("fetch_failed", FETCH_FAILED)
    return NormalizedInput(input_type=InputType.URL, text=text[:MAX_TEXT_CHARS], source_url=safe)


def normalize_image(image_b64: str, mime: str, ocr: Callable | None = None) -> NormalizedInput:
    if mime not in MAGIC:
        raise InputError("bad_input", "Only PNG and JPEG images are supported.")
    if len(image_b64 or "") > MAX_IMAGE_BYTES * 4 // 3 + 4:
        raise InputError("bad_input", "That image is too large. The limit is 5 MB.")
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise InputError("bad_input", "I couldn't decode that image. Try uploading it again.")
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise InputError("bad_input", "That image is empty or larger than 5 MB.")
    if not raw.startswith(MAGIC[mime]):
        raise InputError("bad_input", "That file doesn't look like the image type it claims to be.")

    if ocr is None:
        from app.agents import run_ocr as ocr
    result = ocr(raw, mime)
    if not result.is_legible or not result.text.strip():
        raise InputError("unreadable_image", "I couldn't read any text in that image. Try a sharper screenshot.")
    out = result.to_normalized_input()
    out.text = out.text[:MAX_TEXT_CHARS]
    return out
