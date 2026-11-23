"""SSRF protection and DNS-rebinding-safe HTTP transport for outbound webhooks."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from data_collector.domain.exceptions import ValidationError


def _is_disallowed_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_and_pin_url(
    url: str, *, allow_localhost_dev: bool = False
) -> tuple[str, str, int, str]:
    """Validate URL and resolve DNS once, returning (scheme, host, port, pinned_ip)."""
    if not url or any(ord(c) < 32 for c in url):
        raise ValidationError("Invalid webhook URL")
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.fragment:
        raise ValidationError("Webhook URL must not contain userinfo or fragments")
    if parsed.scheme != "https" and not (
        allow_localhost_dev
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        raise ValidationError("Webhook URL must use https://")

    host = parsed.hostname
    if not host:
        raise ValidationError("Webhook URL must include a valid hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Direct IP literal check
    try:
        ip = ipaddress.ip_address(host)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if _is_disallowed_ip(str(ip)) and not (allow_localhost_dev and ip.is_loopback):
            raise ValidationError("Webhook URL target IP is not permitted")
        return parsed.scheme, host, port, str(ip)
    except ValueError:
        pass

    if host.lower() in {"localhost", "metadata.google.internal"} and not (
        allow_localhost_dev and host.lower() == "localhost"
    ):
        raise ValidationError("Webhook URL hostname is not permitted")

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError("Webhook hostname could not be resolved") from exc

    pinned_ip: str | None = None
    for info in infos:
        addr = str(info[4][0])
        ip = ipaddress.ip_address(addr)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if _is_disallowed_ip(str(ip)) and not (allow_localhost_dev and ip.is_loopback):
            raise ValidationError("Webhook URL resolves to a disallowed private/internal IP")
        if pinned_ip is None:
            pinned_ip = str(ip)

    if pinned_ip is None:
        raise ValidationError("Webhook hostname resolved to no usable addresses")
    return parsed.scheme, host, port, pinned_ip


def validate_outbound_url(url: str, *, allow_localhost_dev: bool = False) -> str:
    """Validate an outbound webhook URL against SSRF rules."""
    resolve_and_pin_url(url, allow_localhost_dev=allow_localhost_dev)
    return url


def post_webhook_safe(
    url: str,
    *,
    content: bytes,
    headers: dict[str, str],
    allow_localhost_dev: bool = False,
    http_client: httpx.Client | None = None,
    max_response_bytes: int = 65536,
) -> int:
    """Connect directly to the validated pinned IP with redirects disabled."""
    scheme, host, port, pinned_ip = resolve_and_pin_url(
        url, allow_localhost_dev=allow_localhost_dev
    )
    parsed = urlparse(url)
    path_and_query = parsed.path or "/"
    if parsed.query:
        path_and_query = f"{path_and_query}?{parsed.query}"

    ip_literal = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    pinned_url = f"{scheme}://{ip_literal}:{port}{path_and_query}"
    req_headers = {**headers, "Host": host}
    extensions: dict[str, Any] = {"sni_hostname": host} if scheme == "https" else {}

    if http_client is not None:
        resp = http_client.post(
            pinned_url,
            content=content,
            headers=req_headers,
            extensions=extensions,
        )
        return int(resp.status_code)

    timeout = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)
    with (
        httpx.Client(follow_redirects=False, timeout=timeout) as client,
        client.stream(
            "POST",
            pinned_url,
            content=content,
            headers=req_headers,
            extensions=extensions,
        ) as resp,
    ):
        if 300 <= resp.status_code < 400:
            raise ValidationError("Webhook redirects are prohibited")
        total = 0
        for chunk in resp.iter_bytes(8192):
            total += len(chunk)
            if total > max_response_bytes:
                break
        return int(resp.status_code)
