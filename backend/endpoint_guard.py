"""The URL guard. Nothing is POSTed until `validate_endpoint` returns.

A user-supplied URL that the server then requests is SSRF: the same class of
trust problem as generated SQL. Scheme, resolved address, pinned IP, no
redirects, and a port allowlist are what actually stop a request to
instance metadata.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

ALLOWED_PORTS = frozenset({80, 443, 8000, 8080, 11434, 1234})
DEFAULT_PATH = "/v1/chat/completions"

# Hostnames that exist only to reach cloud metadata. Checking the name
# before DNS means a laptop that cannot resolve `metadata.google.internal`
# still refuses it for the same reason a GCP box would.
_BLOCKED_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "metadata.google.com",
        "kubernetes.default",
        "kubernetes.default.svc",
        "kubernetes.default.svc.cluster.local",
    }
)

_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("169.254.169.250"),
        ipaddress.ip_address("169.254.169.253"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


class EndpointError(Exception):
    """The URL is not safe to POST to. `code` is stable; `message` is for humans."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidatedEndpoint:
    """A URL that passed the guard, plus the address we will actually connect to.

    `url` keeps the original hostname so the Host header and TLS SNI stay
    correct. `ip` is the address that was judged — connecting to it, rather
    than resolving again, is what closes DNS rebinding.
    """

    url: str
    host: str
    ip: str
    port: int
    scheme: str


def validate_endpoint(url: str) -> str:
    """Raise EndpointError if the URL is not safe to POST to. Return it normalised."""
    return inspect_endpoint(url).url


def inspect_endpoint(url: str) -> ValidatedEndpoint:
    raw = (url or "").strip()
    if not raw:
        raise EndpointError("invalid_url", "endpoint URL is required")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise EndpointError(
            "bad_scheme",
            f"{scheme or 'missing'}:// is not allowed. Use https, or http only "
            "for a loopback address.",
        )
    if parsed.username is not None or parsed.password is not None:
        raise EndpointError("credentials_in_url", "do not put credentials in the URL")

    host = parsed.hostname
    if not host:
        raise EndpointError("invalid_url", "endpoint URL has no host")
    host = host.lower().rstrip(".")
    if host in _BLOCKED_HOSTS:
        raise EndpointError("blocked_host", f"{host} is a metadata endpoint")

    port = parsed.port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise EndpointError(
            "bad_port",
            f"port {port} is not allowed. Use 443, 80, 8000, 8080, 11434, or 1234.",
        )

    addresses = _resolve(host)
    allow_private = os.environ.get("PLUMB_ALLOW_PRIVATE_ENDPOINTS", "").strip() == "1"
    for address in addresses:
        _reject_address(address, scheme=scheme, allow_private=allow_private)

    path = parsed.path or ""
    if path in ("", "/"):
        path = DEFAULT_PATH
    # Keep a query string (some gateways put a version flag there) but drop
    # the fragment. The audit log never sees this URL; only the host.
    normalised = urlunparse(
        (scheme, parsed.netloc.lower(), path, "", parsed.query, "")
    )
    pinned = addresses[0]
    return ValidatedEndpoint(
        url=normalised,
        host=host,
        ip=str(pinned),
        port=port,
        scheme=scheme,
    )


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    literal = _parse_ip(host)
    if literal is not None:
        return [literal]
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise EndpointError("unresolved_host", f"could not resolve {host}") from e
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for record in records:
        packed = record[4][0]
        try:
            address = ipaddress.ip_address(packed)
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        key = str(address)
        if key in seen:
            continue
        seen.add(key)
        addresses.append(address)
    if not addresses:
        raise EndpointError("unresolved_host", f"could not resolve {host}")
    return addresses


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    # http://2852039166/ is 169.254.169.254 written as a single integer.
    if host.isdigit():
        try:
            return ipaddress.IPv4Address(int(host))
        except (ValueError, ipaddress.AddressValueError):
            return None
    return None


def _reject_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    scheme: str,
    allow_private: bool,
) -> None:
    if address in _METADATA_ADDRESSES:
        raise EndpointError("metadata_address", "cloud metadata addresses are not allowed")
    if address.is_unspecified:
        raise EndpointError("bad_address", "unspecified addresses are not allowed")
    if address.is_multicast:
        raise EndpointError("bad_address", "multicast addresses are not allowed")
    if address.is_reserved and not address.is_private and not address.is_loopback:
        raise EndpointError("bad_address", "reserved addresses are not allowed")
    if address.is_link_local:
        raise EndpointError("link_local", "link-local addresses are not allowed")
    if address.is_loopback:
        if scheme == "https":
            raise EndpointError(
                "loopback_https",
                "loopback over https is not allowed; use http for local servers",
            )
        return
    if address.is_private or not address.is_global:
        if allow_private:
            return
        raise EndpointError(
            "private_address",
            "private addresses are not allowed. Set PLUMB_ALLOW_PRIVATE_ENDPOINTS=1 "
            "to reach an internal gateway on purpose.",
        )
    if scheme != "https":
        raise EndpointError(
            "bad_scheme",
            "http is only allowed for loopback. Use https for any other host.",
        )
