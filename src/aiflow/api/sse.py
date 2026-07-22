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
        self._changed = threading.Condition(self._lock)

    def publish(self, event_type: str, data: dict[str, Any]) -> ServerEvent:
        with self._changed:
            event = ServerEvent(self._next_id, event_type, dict(data))
            self._next_id += 1
            self._events.append(event)
            self._changed.notify_all()
            return event

    def replay(self, last_event_id: str) -> Replay:
        with self._lock:
            return self._replay_locked(last_event_id)

    def wait_after(self, last_event_id: str, *, timeout: float) -> Replay:
        with self._changed:
            replay = self._replay_locked(last_event_id)
            if replay.reset or replay.events:
                return replay
            self._changed.wait(timeout=max(0.0, timeout))
            return self._replay_locked(last_event_id)

    @property
    def latest_id(self) -> int:
        with self._lock:
            return self._events[-1].event_id if self._events else 0

    def _replay_locked(self, last_event_id: str) -> Replay:
        retained = tuple(self._events)
        if not last_event_id:
            return Replay(retained)
        try:
            cursor = int(last_event_id)
        except ValueError:
            return Replay((), reset=True)
        latest = retained[-1].event_id if retained else 0
        if cursor > latest:
            return Replay((), reset=True)
        if retained and cursor < retained[0].event_id - 1:
            return Replay((), reset=True)
        return Replay(tuple(event for event in retained if event.event_id > cursor))
