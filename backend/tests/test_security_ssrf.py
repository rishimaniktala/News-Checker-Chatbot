"""Extra SSRF and URL-shape attacks beyond test_url_safety.py."""

import pytest

from app.url_safety import UnsafeUrl, check_url

PUBLIC = lambda host: ["93.184.216.34"]


def blocked(url):
    with pytest.raises(UnsafeUrl):
        check_url(url, resolver=PUBLIC)


@pytest.mark.parametrize("url", [
    "http://0", "http://0.0.0.0", "http://[::]", "http://[::ffff:127.0.0.1]", "http://[::ffff:0:0]",
    "http://localhost.", "http://LOCALHOST", "http://LocalHost.:80", "http://a.localhost.",
    "http://[fe80::1%25eth0]", "http://[fe80::1%eth0]", "http://[::1%25lo]",
    "http://0x7f.1", "http://0x7f000001.", "http://017700000001", "http://127.0.0.1.",
    "http://[0:0:0:0:0:0:0:1]",
    "http://169.254.169.254.", "http://[fd00:ec2::254]", "http://192.0.0.192",
    "HTTP://127.0.0.1", "http://127.0.0.1:8080", "http://127.0.0.1:80@evil.test",
])
def test_private_forms_blocked(url):
    blocked(url)


@pytest.mark.parametrize("url", [
    "http://google.com@127.0.0.1", "http://google.com:80@127.0.0.1/", "http://user@example.com",
    "http://example.com%40127.0.0.1@evil.test", "https://@example.com", "https://:@example.com",
])
def test_userinfo_tricks_blocked(url):
    blocked(url)


@pytest.mark.parametrize("url", [
    "http://example.com:0", "http://example.com:-1", "http://example.com:80:80", "http://example.com:abc",
    "http://example.com:65536", "http://[::1", "http://::1", "http://[example.com]",
])
def test_malformed_authority_blocked(url):
    blocked(url)


@pytest.mark.parametrize("url", [
    "gopher://example.com", "dict://example.com", "data:text/html,x", "//example.com", "example.com",
    "http:/example.com", "http:example.com", "https:///example.com", "ws://example.com",
])
def test_odd_schemes_and_shapes_blocked(url):
    blocked(url)


def test_idn_resolves_via_resolver_and_stays_public():
    seen = []

    def resolver(host):
        seen.append(host)
        return ["93.184.216.34"]

    check_url("http://bücher.example/", resolver=resolver)
    assert seen == ["bücher.example"]


def test_idn_host_resolving_private_is_blocked():
    with pytest.raises(UnsafeUrl):
        check_url("http://xn--bcher-kva.example/", resolver=lambda h: ["10.0.0.1"])


def test_uppercase_host_is_lowercased_for_lookup():
    seen = []
    check_url("HTTPS://EXAMPLE.COM/Path", resolver=lambda h: seen.append(h) or ["93.184.216.34"])
    assert seen == ["example.com"]


def test_trailing_dot_public_host_looked_up_without_dot():
    seen = []
    check_url("http://example.com./", resolver=lambda h: seen.append(h) or ["93.184.216.34"])
    assert seen == ["example.com"]


def test_long_label_host_does_not_crash():
    host = "a" * 120 + ".example.com"
    try:
        check_url(f"http://{host}/", resolver=PUBLIC)
    except UnsafeUrl:
        pass


def test_resolver_failure_becomes_friendly_error():
    def boom(host):
        raise UnsafeUrl("I couldn't find that website. Check the link and try again.")

    with pytest.raises(UnsafeUrl):
        check_url("http://nope.example/", resolver=boom)


def test_empty_resolution_blocked():
    with pytest.raises(UnsafeUrl):
        check_url("http://example.com/", resolver=lambda h: [])


@pytest.mark.parametrize("url", [
    "http://exam\tple.com/", "http://example.com/a\nb", "http://example.com/\r\nHost: 127.0.0.1",
    "http://127.0.0.1\n.example.com/", "http://\t127.0.0.1/", "\x00http://example.com",
])
def test_control_chars_never_reach_the_fetcher(url):
    try:
        out = check_url(url, resolver=PUBLIC)
    except UnsafeUrl:
        return
    assert not any(c in out for c in "\t\r\n\x00")


def test_tab_inside_ip_does_not_hide_loopback():
    blocked("http://127.0.\t0.1/")


def test_query_credentials_pass_but_are_kept_verbatim():
    out = check_url("https://example.com/a?token=abc&api_key=xyz", resolver=PUBLIC)
    assert out.endswith("?token=abc&api_key=xyz")


def test_fragment_is_dropped():
    assert "#" not in check_url("https://example.com/a#secret", resolver=PUBLIC)


def test_returned_url_netloc_is_lowercase():
    assert check_url("https://EXAMPLE.com/X", resolver=PUBLIC) == "https://example.com/X"


@pytest.mark.parametrize("url", ["http://example.com\\@127.0.0.1/", "http://127.0.0.1\\@example.com/"])
def test_backslash_with_userinfo_blocked(url):
    blocked(url)


def test_backslash_never_reaches_the_fetcher():
    try:
        out = check_url("http://127.0.0.1\\.example.com/", resolver=PUBLIC)
    except UnsafeUrl:
        return
    assert "\\" not in out


def test_6to4_loopback_blocked():
    blocked("http://[2002:7f00:1::]")


@pytest.mark.parametrize("url", ["http://[64:ff9b::7f00:1]", "http://[64:ff9b::a00:1]", "http://[::127.0.0.1]"])
def test_embedded_ipv4_transition_forms_blocked(url):
    blocked(url)


# ---- HTTP layer checks (main.py, store.py)

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import main, orchestrator, store  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "h.db"))
    monkeypatch.setattr(main, "make_search_fn", lambda settings, budget: None)
    return TestClient(main.app)


@pytest.mark.parametrize("rid", ["x' OR '1'='1", "1; DROP TABLE runs;--", "%27%20OR%201=1", "../../etc/passwd"])
def test_run_lookup_is_parameterized(api, rid):
    store.save_run("real", {"kind": "text"}, [], None, 0.0, 1)
    r = api.get(f"/api/runs/{rid}")
    assert r.status_code == 404
    assert api.get("/api/runs/real").status_code == 200


def test_sql_metacharacters_in_run_data_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "q.db"))
    store.save_run("a", {"text": "'); DROP TABLE runs;--"}, [], None, 0.0, 1)
    assert store.load_run("a")["request"]["text"] == "'); DROP TABLE runs;--"


def test_image_bytes_not_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "i.db"))
    store.save_run("a", {"kind": "image", "image_b64": "AAAA"}, [], None, 0.0, 1)
    assert "AAAA" not in json.dumps(store.load_run("a"))


def test_cors_allows_only_the_dev_origin(api):
    ok = api.get("/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    for origin in ("http://evil.test", "http://localhost:3000.evil.test", "null"):
        r = api.get("/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in r.headers
    pre = api.options("/api/check", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre.headers


def test_cors_sends_no_credentials_header(api):
    r = api.get("/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-credentials" not in r.headers


def test_non_object_body_rejected(api):
    assert api.post("/api/check", json=["x"]).status_code == 422


@pytest.mark.parametrize("body", [{"kind": "text", "text": 123}, {"kind": "url", "url": 5}, {"kind": ["text"]},
                                  {"kind": "image", "image_b64": 7, "mime": "image/png"}])
def test_wrong_typed_fields_end_in_a_clean_error(api, body):
    events = [json.loads(x[6:]) for x in api.post("/api/check", json=body).text.split("\n\n") if x.startswith("data: ")]
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[0]["code"] in {"bad_input", "internal"}
    assert events[-1]["type"] == "done"


def test_oversized_body_rejected_before_parsing(api, monkeypatch):
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: (_ for _ in ()).throw(RuntimeError("stop")))
    r = api.post("/api/check", content=json.dumps({"kind": "text", "text": "a" * 12_000_000}),
                 headers={"Content-Type": "application/json"})
    assert r.status_code in (413, 422)
