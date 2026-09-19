"""The URL guard is the security boundary for a user-supplied endpoint."""

from __future__ import annotations

import ipaddress
import socket

import pytest

from backend.endpoint_guard import (
    EndpointError,
    inspect_endpoint,
    validate_endpoint,
)
from backend.providers import PRESETS, preset_url

REJECTED = [
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "file:///etc/passwd",
    "gopher://internal:70/",
    "https://user:pass@example.com/v1",
    "http://10.0.0.5/v1/chat/completions",
    "https://example.com:22/v1",
]


@pytest.mark.parametrize("url", REJECTED)
def test_rejected(url: str) -> None:
    with pytest.raises(EndpointError):
        validate_endpoint(url)


def test_https_public_host_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    out = validate_endpoint("https://example.com/v1")
    assert out.startswith("https://example.com/")


def test_loopback_http_passes() -> None:
    assert validate_endpoint("http://localhost:1234/v1/chat/completions")
    assert validate_endpoint("http://127.0.0.1:11434/v1/chat/completions")


def test_private_address_passes_only_with_opt_in(monkeypatch) -> None:
    with pytest.raises(EndpointError) as caught:
        validate_endpoint("http://10.0.0.5/v1/chat/completions")
    assert caught.value.code == "private_address"

    monkeypatch.setenv("PLUMB_ALLOW_PRIVATE_ENDPOINTS", "1")
    out = validate_endpoint("http://10.0.0.5/v1/chat/completions")
    assert "10.0.0.5" in out


def test_loopback_https_is_rejected() -> None:
    with pytest.raises(EndpointError) as caught:
        validate_endpoint("https://127.0.0.1/v1")
    assert caught.value.code == "loopback_https"


def test_integer_ipv4_metadata_is_rejected() -> None:
    # 2852039166 == 169.254.169.254
    with pytest.raises(EndpointError):
        validate_endpoint("http://2852039166/latest/meta-data/")


def test_credentials_are_rejected_with_a_clear_reason() -> None:
    with pytest.raises(EndpointError) as caught:
        validate_endpoint("https://user:pass@example.com/v1")
    assert caught.value.code == "credentials_in_url"
    assert "credentials" in caught.value.message


def test_missing_path_gains_the_openai_default() -> None:
    out = validate_endpoint("http://127.0.0.1:11434")
    assert out.endswith("/v1/chat/completions")


def test_pin_keeps_the_hostname_and_the_judged_ip(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    endpoint = inspect_endpoint("https://example.com/v1")
    assert endpoint.ip == "93.184.216.34"
    assert endpoint.host == "example.com"
    assert "example.com" in endpoint.url
    assert "93.184.216.34" not in endpoint.url


def test_every_resolved_address_must_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ],
    )
    with pytest.raises(EndpointError):
        validate_endpoint("https://evil.example/v1")


def test_preset_urls_pass_the_guard(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *_a, **_k: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("1.1.1.1", 443),
            )
        ],
    )
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    for preset in PRESETS:
        validate_endpoint(preset_url(preset))


def test_endpoint_error_carries_code_and_message() -> None:
    with pytest.raises(EndpointError) as caught:
        validate_endpoint("file:///etc/passwd")
    assert caught.value.code == "bad_scheme"
    assert caught.value.message


def test_link_local_range_is_rejected() -> None:
    with pytest.raises(EndpointError) as caught:
        validate_endpoint("http://169.254.1.1/v1")
    assert caught.value.code == "link_local"
    assert ipaddress.ip_address("169.254.1.1").is_link_local
