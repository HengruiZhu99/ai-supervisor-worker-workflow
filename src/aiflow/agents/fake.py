from __future__ import annotations

import copy
from collections import defaultdict, deque
from typing import Any, Iterable, Mapping


class FakeAgentBackend:
    """Deterministic offline backend for controller and acceptance tests."""

    def __init__(self, scripts: Mapping[str, Iterable[Mapping[str, Any]]]) -> None:
        self._scripts: defaultdict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for action, responses in scripts.items():
            self._scripts[str(action)].extend(
                copy.deepcopy([dict(response) for response in responses])
            )
        self.calls = 0

    def run(self, capsule: Mapping[str, Any]) -> dict[str, Any]:
        self.calls += 1
        action = str(capsule.get("action", ""))
        if not action:
            return {"status": "invalid", "error": "action is required"}
        if not self._scripts[action]:
            return {"status": "unsupported", "action": action}
        result = dict(self._scripts[action].popleft())
        return {"action": action, **result}
