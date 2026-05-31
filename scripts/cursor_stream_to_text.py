#!/usr/bin/env python3
"""Convert Cursor stream-json output to readable text.

The Cursor stream schema is CLI-version dependent, so this parser is intentionally
best-effort: it prefers text/delta fields and emits compact markers for tool or
status events when there is no natural text payload.
"""

from __future__ import annotations

import json
import sys


TEXT_KEYS = {"text", "delta"}
STRING_CONTENT_KEYS = {"content", "message"}
EVENT_KEYS = ("type", "event", "name", "status", "tool")


def iter_text(value: object, parent_key: str = ""):
    if isinstance(value, str):
        if parent_key in TEXT_KEYS or (parent_key in STRING_CONTENT_KEYS and "\n" in value):
            yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from iter_text(item, parent_key)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_text(item, key)


def event_marker(data: dict) -> str:
    parts = []
    for key in EVENT_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if not parts:
        return ""
    marker = " ".join(dict.fromkeys(parts))
    return f"\n[{marker}]\n"


def main() -> int:
    previous_text = ""
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            print(raw, end="", flush=True)
            previous_text = ""
            continue

        if isinstance(data, dict):
            if data.get("type") == "user":
                continue
            message = data.get("message")
            if isinstance(message, dict) and message.get("role") == "user":
                continue

        texts = list(iter_text(data))
        if texts:
            for text in texts:
                if text == previous_text:
                    continue
                print(text, end="" if text.endswith("\n") else "\n", flush=True)
                previous_text = text
            continue

        if isinstance(data, dict):
            marker = event_marker(data)
            if marker:
                print(marker, end="", flush=True)
                previous_text = ""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
