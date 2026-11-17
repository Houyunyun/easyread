"""Explicit Host allowlist for local and container deployments (not authentication)."""
from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def host_name(value: str | None) -> str:
    value = (value or "").strip().lower()
    if "://" in value:
        try:
            value = urlsplit(value).hostname or ""
        except ValueError:
            return ""
    elif value.startswith("["):
        value = value[1:].split("]", 1)[0]
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value.rstrip(".")


def allowed_hosts(bind_host: str, extra: str = "") -> frozenset[str]:
    hosts = set(LOOPBACK_HOSTS)
    for value in [bind_host, *extra.split(",")]:
        name = host_name(value)
        if name and name not in ("0.0.0.0", "::", "*"):
            hosts.add(name)
    return frozenset(hosts)


def check_host(headers, hosts: frozenset[str]) -> bool:
    # Reject duplicate or malformed authorities before normalization. An
    # attacker-controlled domain resolving to localhost must not read tokens.
    values = headers.get_all("Host", [])
    if len(values) != 1:
        return False
    host = values[0]
    if not host or any(c.isspace() or c in "/\\@?#" for c in host):
        return False
    try:
        parsed = urlsplit("//" + host)
        name = parsed.hostname
        parsed.port  # Validate brackets and the optional port.
    except ValueError:
        return False
    return bool(name) and host_name(name) in hosts


def check_origin(origin: str | None, host: str) -> bool:
    # HTTPS is terminated by the proxy, which must preserve the original Host.
    # Do not trust arbitrary X-Forwarded-Host / X-Forwarded-Proto headers.
    return origin in (None, f"http://{host}", f"https://{host}")
