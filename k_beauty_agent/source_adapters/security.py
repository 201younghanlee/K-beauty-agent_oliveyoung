from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urlparse


def require_https_url(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    if not isinstance(url, str) or not url or re.search(r"[\\\x00-\x20\x7f]", url):
        raise ValueError("Partner URLs must be well-formed HTTPS URLs")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Partner URL contains an invalid port") from exc
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or port not in {None, 443}:
        raise ValueError("Partner URLs must use HTTPS and must not contain credentials")
    _reject_private_host(host)
    normalized_allowed = {allowed.lower().rstrip(".") for allowed in (allowed_hosts or set())}
    if normalized_allowed and host not in normalized_allowed:
        raise ValueError(f"Partner URL host is not allowlisted: {host}")
    return url


def host_matches(url: str, allowed_hosts: set[str]) -> bool:
    try:
        require_https_url(url, allowed_hosts=allowed_hosts)
    except ValueError:
        return False
    return True


def require_public_dns_resolution(
    url: str,
    *,
    resolver: Callable[..., list[tuple[object, ...]]] = socket.getaddrinfo,
) -> None:
    """Reject partner endpoints resolving to any non-public address."""

    require_https_url(url)
    host = (urlparse(url).hostname or "").rstrip(".").lower()
    try:
        answers = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Partner URL hostname could not be resolved") from exc
    if not answers:
        raise ValueError("Partner URL hostname could not be resolved")
    for answer in answers:
        try:
            address_text = str(answer[4][0])
            address = ipaddress.ip_address(address_text.split("%", 1)[0])
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("Partner URL returned an invalid DNS address") from exc
        if not address.is_global:
            raise ValueError("Partner URL DNS must resolve only to public addresses")


def _reject_private_host(host: str) -> None:
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise ValueError("Partner URL host must be publicly routable")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if "." not in host:
            raise ValueError("Partner URL host must be publicly routable")
        return
    if not address.is_global:
        raise ValueError("Partner URL host must be publicly routable")
