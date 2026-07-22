from __future__ import annotations

import ast
import json
import os
import tempfile
import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from aiflow.quality.architecture import (
    cycle_errors,
    dependencies,
    layer_errors,
    module_name,
)
from aiflow.quality.diff_budget import SOURCE_SUFFIXES, diff_errors, source_lines


DEFAULTS = {
    "python": 450,
    "python_cli_api": 400,
    "shell": 160,
    "typescript_javascript": 450,
    "react_component": 300,
    "function": 100,
    "complexity": 12,
}
IGNORED_PARTS = {".git", ".worktrees", "__pycache__", "node_modules", "backups"}
DEPRECATION_FIELDS = {
    "id",
    "symbol_or_path",
    "replacement",
    "introduced_version",
    "removal_version",
    "removal_deadline",
    "owner",
    "compat_tests",
    "remaining_call_sites",
}
EXCEPTION_FIELDS = {"owner", "reason", "scope", "created", "expires", "removal_target"}


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def complexity(node: ast.AST) -> int:
    branches = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.comprehension)
    score = 1
    for child in ast.walk(node):
        if isinstance(child, branches):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += max(1, len(child.values) - 1)
        elif isinstance(child, ast.Try):
            score += len(child.handlers) + bool(child.orelse) + bool(child.finalbody)
        elif isinstance(child, ast.Match):
            score += len(child.cases)
    return score


def python_metrics(path: Path) -> tuple[list[dict[str, Any]], ast.Module | None]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return [], None
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "logical_lines": max(
                        1, (node.end_lineno or node.lineno) - node.lineno + 1
                    ),
                    "complexity": complexity(node),
                }
            )
    return functions, tree


def imports_compat(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if str(node.module or "").startswith("aiflow.compat"):
                return True
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("aiflow.compat") for alias in node.names):
                return True
    return False


def tiny_forwarder(relative: str, metric: dict[str, Any], tree: ast.Module) -> bool:
    if Path(relative).name in {"__init__.py", "__main__.py"}:
        return False
    body = [node for node in tree.body if not isinstance(node, ast.Expr)]
    return bool(
        metric["logical_lines"] <= 5
        and body
        and all(isinstance(node, (ast.Import, ast.ImportFrom)) for node in body)
    )


class QualityChecker:
    def __init__(self, root: Path, *, diff_base: str = "HEAD") -> None:
        self.root = root.resolve()
        self.diff_base = diff_base
        self.config_dir = self.root / ".aiflow"
        self.baseline_file = self.config_dir / "quality-baseline.json"
        self.policy = self._policy()

    def _toml(self, name: str) -> dict[str, Any]:
        path = self.config_dir / name
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, tomllib.TOMLDecodeError) as exc:
            return {"_parse_error": str(exc)}

    def _policy(self) -> dict[str, Any]:
        config = self._toml("quality.toml")
        files = (
            config.get("files", {}) if isinstance(config.get("files", {}), dict) else {}
        )
        functions = config.get("functions", {})
        limits = dict(DEFAULTS)
        for key in (
            "python",
            "python_cli_api",
            "shell",
            "typescript_javascript",
            "react_component",
        ):
            section = files.get(key, {}) if isinstance(files, dict) else {}
            if isinstance(section, dict) and "hard_logical_lines" in section:
                limits[key] = int(section["hard_logical_lines"])
        if isinstance(functions, dict):
            limits["function"] = int(
                functions.get("hard_logical_lines", limits["function"])
            )
            limits["complexity"] = int(
                functions.get("hard_complexity", limits["complexity"])
            )
        return {
            "limits": limits,
            "exceptions": config.get("exception", []),
            "raw": config,
        }

    def _sources(self) -> Iterable[Path]:
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(self.root)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            yield path

    def _file_limit(self, relative: str) -> int:
        suffix = Path(relative).suffix.lower()
        limits = self.policy["limits"]
        if suffix == ".py":
            if "/cli/" in f"/{relative}" or "/api/" in f"/{relative}":
                return limits["python_cli_api"]
            return limits["python"]
        if suffix in {".sh", ".bash"}:
            return limits["shell"]
        if suffix in {".jsx", ".tsx"}:
            return limits["react_component"]
        return limits["typescript_javascript"]

    def _measure(self) -> dict[str, Any]:
        files: dict[str, Any] = {}
        for path in sorted(self._sources()):
            relative = path.relative_to(self.root).as_posix()
            functions, tree = (
                python_metrics(path) if path.suffix == ".py" else ([], None)
            )
            files[relative] = {
                "logical_lines": source_lines(path),
                "hard_limit": self._file_limit(relative),
                "functions": functions,
                "parse_ok": tree is not None if path.suffix == ".py" else True,
            }
        return files

    def baseline(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "captured_at": date.today().isoformat(),
            "files": self._measure(),
        }
        _atomic_json(self.baseline_file, payload)
        return payload

    def _baseline(self) -> dict[str, Any]:
        try:
            return json.loads(self.baseline_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"files": {}}

    def _exceptions(self) -> list[str]:
        errors: list[str] = []
        entries = self.policy.get("exceptions", [])
        if not isinstance(entries, list):
            return ["quality exception table must be an array"]
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not EXCEPTION_FIELDS <= entry.keys():
                errors.append(
                    f"quality exception {index} lacks required ownership/expiry fields"
                )
                continue
            try:
                expiry = date.fromisoformat(str(entry["expires"]))
            except ValueError:
                errors.append(f"quality exception {index} has invalid expiry")
                continue
            if expiry < date.today():
                errors.append(
                    f"expired quality exception: {entry['scope']} expired {expiry}"
                )
        return errors

    def _deprecations(self) -> list[str]:
        config = self._toml("deprecations.toml")
        if "_parse_error" in config:
            return [f"invalid deprecations.toml: {config['_parse_error']}"]
        errors: list[str] = []
        entries = config.get("deprecation", [])
        if not isinstance(entries, list):
            return ["deprecation table must be an array"]
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not DEPRECATION_FIELDS <= entry.keys():
                errors.append(
                    f"deprecation {index} lacks replacement/owner/tests/usage/expiry"
                )
                continue
            try:
                deadline = date.fromisoformat(str(entry["removal_deadline"]))
            except ValueError:
                errors.append(
                    f"deprecation {entry.get('id', index)} has invalid removal deadline"
                )
                continue
            if deadline < date.today():
                errors.append(
                    f"expired deprecation: {entry['id']} deadline was {deadline.isoformat()}"
                )
            for test in entry["compat_tests"]:
                relative = str(test)
                if not (self.root / relative).is_file():
                    errors.append(
                        f"compatibility test missing: {entry['id']} -> {relative}"
                    )
            observed = self._deprecation_usage(str(entry["symbol_or_path"]))
            declared = int(entry["remaining_call_sites"])
            if observed != declared:
                errors.append(
                    f"deprecation usage count mismatch: {entry['id']} "
                    f"declares {declared}, observed {observed}"
                )
        return errors

    def _deprecation_usage(self, symbol_or_path: str) -> int:
        token = Path(symbol_or_path).name
        excluded = {
            symbol_or_path,
            "src/aiflow/quality/config.py",
        }
        count = 0
        for path in self._sources():
            relative = path.relative_to(self.root).as_posix()
            if relative in excluded or relative.startswith("tests/"):
                continue
            if path.suffix not in {".py", ".sh", ".bash"}:
                continue
            if token in path.read_text(encoding="utf-8", errors="replace"):
                count += 1
        return count

    def _architecture(self, files: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        graph: dict[str, set[str]] = {}
        authorities: dict[str, list[str]] = {}
        for relative, metric in files.items():
            if not relative.endswith(".py"):
                continue
            errors.extend(
                self._inspect_architecture_file(relative, metric, graph, authorities)
            )
        errors.extend(cycle_errors(graph))
        for name, paths in authorities.items():
            if len(paths) > 1:
                errors.append(
                    f"duplicate class authority {name}: {', '.join(sorted(paths))}"
                )
        return errors

    def _inspect_architecture_file(
        self,
        relative: str,
        metric: dict[str, Any],
        graph: dict[str, set[str]],
        authorities: dict[str, list[str]],
    ) -> list[str]:
        _, tree = python_metrics(self.root / relative)
        if tree is None:
            return []
        errors: list[str] = []
        core = relative.startswith("src/aiflow/") and "/compat/" not in f"/{relative}"
        if core and imports_compat(tree):
            errors.append(f"core import of compat: {relative}")
        if tiny_forwarder(relative, metric, tree):
            errors.append(f"tiny forwarder cannot game architecture limits: {relative}")
        if not core:
            return errors
        module = module_name(relative)
        graph[module] = dependencies(tree)
        errors.extend(layer_errors(relative, module, graph[module]))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and not node.name.endswith("Error"):
                authorities.setdefault(node.name, []).append(relative)
        return errors

    def check(self) -> dict[str, Any]:
        files = self._measure()
        previous = self._baseline().get("files", {})
        diff_failures, applied = diff_errors(
            self.root, self.policy["raw"], base=self.diff_base
        )
        errors = (
            self._exceptions()
            + self._deprecations()
            + self._architecture(files)
            + diff_failures
        )
        for relative, metric in files.items():
            old = previous.get(relative, {}) if isinstance(previous, dict) else {}
            errors.extend(self._file_errors(relative, metric, old))
            errors.extend(self._function_errors(relative, metric, old))
        return {
            "ok": not errors,
            "errors": sorted(errors),
            "files_checked": len(files),
            "exceptions_applied": sorted(applied),
        }

    @staticmethod
    def _file_errors(
        relative: str, metric: dict[str, Any], old: dict[str, Any]
    ) -> list[str]:
        lines, limit = metric["logical_lines"], metric["hard_limit"]
        old_lines = int(old.get("logical_lines", 0)) if isinstance(old, dict) else 0
        if lines <= limit:
            return []
        if not old or old_lines <= limit:
            return [f"file hard limit exceeded: {relative} has {lines}>{limit}"]
        if lines > old_lines:
            return [
                f"oversized no-growth violation: {relative} grew {old_lines}->{lines}"
            ]
        return []

    def _function_errors(
        self, relative: str, metric: dict[str, Any], old: dict[str, Any]
    ) -> list[str]:
        prior = self._prior_functions(old)
        errors: list[str] = []
        limits = self.policy["limits"]
        fields = (
            ("logical_lines", "function hard limit", limits["function"]),
            ("complexity", "complexity hard limit", limits["complexity"]),
        )
        for function in metric.get("functions", []):
            old_function = prior.get(function["name"], {})
            for field, label, hard in fields:
                value = int(function[field])
                if value > hard and value > int(old_function.get(field, 0)):
                    errors.append(
                        f"{label}: {relative}:{function['line']} "
                        f"{function['name']} has {value}>{hard}"
                    )
        return errors

    @staticmethod
    def _prior_functions(old: dict[str, Any]) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for item in old.get("functions", []) if isinstance(old, dict) else []:
            name = str(item.get("name", ""))
            prior = result.setdefault(name, {"logical_lines": 0, "complexity": 0})
            for field in ("logical_lines", "complexity"):
                prior[field] = max(prior[field], int(item.get(field, 0)))
        return result
