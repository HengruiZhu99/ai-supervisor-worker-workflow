from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServerEvent:
    event_id: int
    event_type: str
    data: dict[str, Any]

    def encode(self) -> str:
        payload = json.dumps(self.data, separators=(",", ":"), sort_keys=True)
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {payload}\n\n"


@dataclass(frozen=True)
class Replay:
    events: tuple[ServerEvent, ...]
    reset: bool = False


class EventBuffer:
    def __init__(self, *, limit: int = 512) -> None:
        if limit < 1:
            raise ValueError("event retention must be positive")
        self._events: deque[ServerEvent] = deque(maxlen=limit)
        self._next_id = 1
        self._lock = threading.Lock()

    def publish(self, event_type: str, data: dict[str, Any]) -> ServerEvent:
        with self._lock:
            event = ServerEvent(self._next_id, event_type, dict(data))
            self._next_id += 1
            self._events.append(event)
            return event

    def replay(self, last_event_id: str) -> Replay:
        with self._lock:
            retained = tuple(self._events)
        if not last_event_id:
            return Replay(retained)
        try:
            cursor = int(last_event_id)
        except ValueError:
            return Replay((), reset=True)
        if retained and cursor < retained[0].event_id - 1:
            return Replay((), reset=True)
        return Replay(tuple(event for event in retained if event.event_id > cursor))
