from __future__ import annotations

import hmac
import ipaddress
from dataclasses import dataclass
from typing import Mapping


class SecurityError(ValueError):
    """An API request violates the local-server security contract."""


def validate_bind(host: str, *, allow_remote: bool = False) -> str:
    normalized = host.strip().strip("[]")
    if normalized == "localhost":
        return host
    try:
        loopback = ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        loopback = False
    if not loopback and not allow_remote:
        raise SecurityError("non-loopback GUI bind requires --allow-remote")
    return host


def _header(headers: Mapping[str, str], name: str) -> str:
    direct = headers.get(name)
    if direct is not None:
        return str(direct)
    lowered = name.lower()
    return next((str(value) for key, value in headers.items() if key.lower() == lowered), "")


@dataclass(frozen=True)
class RequestSecurity:
    token: str
    host: str
    port: int
    max_body_bytes: int = 64 * 1024

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{host}:{self.port}"

    @property
    def origin(self) -> str:
        return f"http://{self.authority}"

    def authorize_read(self, headers: Mapping[str, str]) -> None:
        if _header(headers, "Host") != self.authority:
            raise SecurityError("request Host does not match this project server")

    def authorize_mutation(self, headers: Mapping[str, str]) -> None:
        self.authorize_read(headers)
        if _header(headers, "Origin") != self.origin:
            raise SecurityError("mutation Origin does not match this project server")
        supplied = _header(headers, "X-AIFLOW-Token")
        if not supplied or not hmac.compare_digest(supplied, self.token):
            raise SecurityError("invalid project mutation token")
        if _header(headers, "Content-Type").split(";", 1)[0].strip() != "application/json":
            raise SecurityError("mutations require application/json")
        raw_length = _header(headers, "Content-Length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise SecurityError("invalid Content-Length") from exc
        if length < 0 or length > self.max_body_bytes:
            raise SecurityError("mutation body exceeds the configured limit")
