from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def payload_checksum(payload: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "checksum"}
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def signed(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["checksum"] = payload_checksum(result)
    return result


def verify_signed(payload: Mapping[str, Any], label: str) -> None:
    if payload.get("checksum") != payload_checksum(payload):
        raise ValueError(f"checksum mismatch for {label}")


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload
