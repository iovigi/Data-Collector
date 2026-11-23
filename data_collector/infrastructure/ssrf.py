"""SSRF protection for outbound webhook URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from data_collector.domain.exceptions import ValidationError


def _is_disallowed_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_outbound_url(url: str, *, allow_localhost_dev: bool = False) -> str:
    """Validate an outbound webhook URL against SSRF rules (HTTPS only, no private/metadata IPs)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (
        allow_localhost_dev
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        raise ValidationError("Webhook URL must use https://")
    host = parsed.hostname
    if not host:
        raise ValidationError("Webhook URL must include a valid hostname")

    # Direct IP literal check
    try:
        ip = ipaddress.ip_address(host)
        if _is_disallowed_ip(host) and not (allow_localhost_dev and ip.is_loopback):
            raise ValidationError("Webhook URL target IP is not permitted")
        return url
    except ValueError:
        pass

    if host.lower() in {"localhost", "metadata.google.internal"} and not allow_localhost_dev:
        raise ValidationError("Webhook URL hostname is not permitted")

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError("Webhook hostname could not be resolved") from exc

    for info in infos:
        addr = info[4][0]
        if _is_disallowed_ip(str(addr)) and not allow_localhost_dev:
            raise ValidationError("Webhook URL resolves to a disallowed private/internal IP")
    return url
