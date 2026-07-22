from __future__ import annotations

from typing import Any, Iterable

from aiflow.api.service import ApiService
from aiflow.identity.context import ProjectContext


class ReadOnlyHubError(RuntimeError):
    """The read-only hub was asked to mutate a project."""


class ProjectHub:
    def __init__(self, projects: Iterable[ProjectContext]) -> None:
        self._services = tuple(ApiService(project) for project in projects)

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "read_only": True,
            "projects": [service.project() for service in self._services],
        }

    def mutate(self, action: str, payload: dict[str, Any]) -> None:
        del action, payload
        raise ReadOnlyHubError("multi-project hub is read-only; use the selected project server")
