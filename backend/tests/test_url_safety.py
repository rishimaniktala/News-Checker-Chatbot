import pytest

from app.url_safety import UnsafeUrl, check_url

PUBLIC = lambda host: ["93.184.216.34"]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1", "http://169.254.169.254/latest", "http://[::1]", "http://2130706433",
    "http://0x7f000001", "http://0177.0.0.1", "http://127.1", "http://10.0.0.5", "http://192.168.1.1",
    "http://172.16.0.1", "http://0.0.0.0", "http://224.0.0.1", "http://[::ffff:127.0.0.1]",
    "http://[::ffff:7f00:1]", "http://[fe80::1]", "http://[fc00::1]", "http://localhost",
    "http://foo.localhost", "http://LOCALHOST./", "http://router.local", "http://100.64.0.1",
])
def test_private_hosts_rejected(url):
    with pytest.raises(UnsafeUrl) as e:
        check_url(url, resolver=PUBLIC)
    assert "private or internal" in e.value.message


@pytest.mark.parametrize("url", [
    "ftp://x", "file:///etc/passwd", "javascript:alert(1)", "", "   ", "http://",
    "https://user:pw@example.com", "https://example.com:22", "https://example.com:99999",
    "https://example.com/" + "a" * 2000,
])
def test_bad_shapes_rejected(url):
    with pytest.raises(UnsafeUrl):
        check_url(url, resolver=PUBLIC)


def test_rebinding_mixed_addresses_rejected():
    with pytest.raises(UnsafeUrl):
        check_url("https://evil.example", resolver=lambda h: ["93.184.216.34", "10.0.0.1"])


def test_private_ipv6_from_dns_rejected():
    with pytest.raises(UnsafeUrl):
        check_url("https://evil.example", resolver=lambda h: ["::ffff:10.0.0.1"])


def test_unresolvable_host_rejected():
    with pytest.raises(UnsafeUrl):
        check_url("https://x.example", resolver=lambda h: [])


@pytest.mark.parametrize("url,out", [
    ("https://Example.com/a?b=1#frag", "https://example.com/a?b=1"),
    ("http://example.com:8080/x", "http://example.com:8080/x"),
    ("  https://example.com:443  ", "https://example.com:443"),
])
def test_public_urls_pass(url, out):
    assert check_url(url, resolver=PUBLIC) == out
