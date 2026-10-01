from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from bugpilot_core.config import Settings


PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


class TargetValidationError(ValueError):
    pass


def validate_scan_target(url: str, settings: Settings) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise TargetValidationError("Only http and https URLs are allowed.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise TargetValidationError("URL is missing a hostname.")
    if host in {"localhost"} and settings.block_private_targets:
        # Local demo apps are allowed in development.
        if settings.bugpilot_env == "development":
            return url
        raise TargetValidationError("Localhost targets are blocked outside development.")

    suffixes = settings.allowed_suffixes
    if suffixes and not any(host == s or host.endswith("." + s) for s in suffixes):
        raise TargetValidationError("Host is not on the organization allowlist.")

    if settings.block_private_targets and settings.bugpilot_env != "development":
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise TargetValidationError(f"Could not resolve host: {host}") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if any(ip in net for net in PRIVATE_NETWORKS):
                raise TargetValidationError("Private or link-local targets are blocked.")
    return url
