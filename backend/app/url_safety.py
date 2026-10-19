"""SSRF guard. check_url() runs before any URL is handed to the fetcher."""

import ipaddress
import socket
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

MAX_URL_CHARS = 2000
ALLOWED_PORTS = {80, 443, 8080, 8443}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain")

PRIVATE_MSG = "That link points to a private or internal address, so I won't fetch it."
BAD_LINK_MSG = "That doesn't look like a valid web link. Paste a full http or https address."


class UnsafeUrl(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _resolve(host: str) -> list[str]:
    try:
        return [info[4][0] for info in socket.getaddrinfo(host, None)]
    except socket.gaierror:
        raise UnsafeUrl("I couldn't find that website. Check the link and try again.")


def _legacy_ipv4(host: str) -> str | None:
    """Parse inet_aton forms (decimal, hex, octal, short dotted) that getaddrinfo accepts."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    nums = []
    for p in parts:
        try:
            nums.append(int(p, 16) if p.lower().startswith("0x") else int(p, 8) if len(p) > 1 and p[0] == "0" else int(p))
        except ValueError:
            return None
    *head, last = nums
    if any(not 0 <= n <= 255 for n in head) or not 0 <= last < 256 ** (5 - len(nums)):
        return None
    value = last
    for i, n in enumerate(head):
        value |= n << (8 * (3 - i))
    return str(ipaddress.IPv4Address(value))


def _is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address):
        ip = ip.ipv4_mapped or ip
    return ip.is_global and not ip.is_multicast


def check_url(url: str, resolver: Callable[[str], list[str]] = _resolve) -> str:
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_CHARS:
        raise UnsafeUrl(BAD_LINK_MSG)
    try:
        parts = urlsplit(url)
        port = parts.port
        host = (parts.hostname or "").rstrip(".").lower()
    except ValueError:
        raise UnsafeUrl(BAD_LINK_MSG)
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise UnsafeUrl(BAD_LINK_MSG)
    if "@" in parts.netloc:
        raise UnsafeUrl("Links with a username or password in them aren't supported.")
    if port is not None and port not in ALLOWED_PORTS:
        raise UnsafeUrl("That link uses an unusual port, so I won't fetch it.")
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeUrl(PRIVATE_MSG)

    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        legacy = _legacy_ipv4(host)
        addrs = [legacy] if legacy else resolver(host)
    if not addrs or not all(_is_public(a) for a in addrs):
        raise UnsafeUrl(PRIVATE_MSG)

    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))
