from __future__ import annotations

import copy
from collections import defaultdict, deque
from typing import Any, Callable, Iterable, Mapping


ResponseFactory = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ScriptedResponse = Mapping[str, Any] | ResponseFactory


class FakeAgentBackend:
    """Deterministic offline backend for controller and acceptance tests."""

    def __init__(self, scripts: Mapping[str, Iterable[ScriptedResponse]]) -> None:
        self._scripts: defaultdict[str, deque[ScriptedResponse]] = defaultdict(deque)
        for action, responses in scripts.items():
            self._scripts[str(action)].extend(
                self._copy(response) for response in responses
            )
        self.calls = 0

    @staticmethod
    def _copy(response: ScriptedResponse) -> ScriptedResponse:
        return response if callable(response) else copy.deepcopy(dict(response))

    def run(self, capsule: Mapping[str, Any]) -> dict[str, Any]:
        self.calls += 1
        action = str(capsule.get("action", ""))
        if not action:
            return {"status": "invalid", "error": "action is required"}
        if not self._scripts[action]:
            return {"status": "unsupported", "action": action}
        response = self._scripts[action].popleft()
        result = dict(response(capsule) if callable(response) else response)
        return {"action": action, **result}
