"""WSGI middleware: real client IP behind Cloudflare without trusting spoofable headers.

``CF-Connecting-IP`` is honoured only when the TCP peer (``REMOTE_ADDR`` as seen by IIS)
is inside Cloudflare's published edge ranges. Requests that reach the origin directly keep
their real peer address, and any client-supplied ``CF-Connecting-IP`` /
``X-Forwarded-For`` header is ignored for them.

Cloudflare publishes the ranges at https://www.cloudflare.com/ips-v4 and /ips-v6; they
change rarely. ``DC_CLOUDFLARE_RANGES`` (comma separated) overrides the built-in list.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Callable, Iterable
from typing import Any

_DEFAULT_RANGES = (
    "173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,"
    "108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,"
    "162.158.0.0/15,104.16.0.0/13,104.24.0.0/14,172.64.0.0/13,131.0.72.0/22,"
    "2400:cb00::/32,2606:4700::/32,2803:f800::/32,2405:b500::/32,2405:8100::/32,"
    "2a06:98c0::/29,2c0f:f248::/32"
)

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_ranges(raw: str) -> list[Network]:
    return [ipaddress.ip_network(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_cloudflare_peer(peer: str, ranges: Iterable[Network]) -> bool:
    ip = _parse_ip(peer)
    return ip is not None and any(ip in net for net in ranges)


class CloudflareClientIPMiddleware:
    """Rewrite REMOTE_ADDR from CF-Connecting-IP only for verified Cloudflare peers."""

    def __init__(self, app: Callable[..., Any], ranges: Iterable[Network] | None = None) -> None:
        self.app = app
        self.ranges = list(
            ranges
            if ranges is not None
            else parse_ranges(os.environ.get("DC_CLOUDFLARE_RANGES", _DEFAULT_RANGES))
        )

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        peer = str(environ.get("REMOTE_ADDR", ""))
        environ["dc.peer_addr"] = peer
        environ["dc.via_cloudflare"] = False
        if is_cloudflare_peer(peer, self.ranges):
            client = _parse_ip(str(environ.get("HTTP_CF_CONNECTING_IP", "")))
            if client is not None:
                environ["REMOTE_ADDR"] = str(client)
                environ["dc.via_cloudflare"] = True
        # Never let a forwarded-for chain influence anything downstream.
        environ.pop("HTTP_X_FORWARDED_FOR", None)
        return self.app(environ, start_response)
