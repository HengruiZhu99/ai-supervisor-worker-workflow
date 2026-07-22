from __future__ import annotations

import ast


LAYER_RANK = {
    "domain": 0,
    "identity": 0,
    "security": 0,
    "state": 1,
    "quality": 1,
    "skills": 1,
    "scheduler": 1,
    "release": 2,
    "agents": 2,
    "integration": 2,
    "controller": 3,
    "api": 4,
    "cli": 5,
    "compat": 6,
}


def module_name(relative: str) -> str:
    parts = relative.removesuffix(".py").split("/")
    selected = parts[parts.index("aiflow") :]
    if selected[-1] == "__init__":
        selected.pop()
    return ".".join(selected)


def dependencies(tree: ast.Module) -> set[str]:
    hidden = type_checking_ranges(tree)
    result: set[str] = set()
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", 0)
        if any(start <= lineno <= end for start, end in hidden):
            continue
        if isinstance(node, ast.ImportFrom) and str(node.module or "").startswith(
            "aiflow"
        ):
            module = str(node.module)
            result.update(
                module if alias.name == "*" else f"{module}.{alias.name}"
                for alias in node.names
            )
        elif isinstance(node, ast.Import):
            result.update(
                alias.name for alias in node.names if alias.name.startswith("aiflow")
            )
    return result


def type_checking_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    return [
        (node.lineno, node.end_lineno or node.lineno)
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    ]


def layer_errors(relative: str, module: str, imported: set[str]) -> list[str]:
    source = module.split(".")[1] if len(module.split(".")) > 1 else ""
    source_rank = LAYER_RANK.get(source)
    errors: list[str] = []
    for dependency in imported:
        parts = dependency.split(".")
        target = parts[1] if len(parts) > 1 else ""
        target_rank = LAYER_RANK.get(target)
        if (
            source_rank is not None
            and target_rank is not None
            and target_rank > source_rank
        ):
            errors.append(
                f"layer violation: {relative} ({source}) imports {dependency} ({target})"
            )
    return errors


def cycle_errors(graph: dict[str, set[str]]) -> list[str]:
    errors: set[str] = set()
    active: list[str] = []
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in active:
            cycle = active[active.index(module) :] + [module]
            errors.add("dependency cycle: " + " -> ".join(cycle))
            return
        if module in visited:
            return
        active.append(module)
        for dependency in graph.get(module, set()):
            resolved = dependency
            while resolved and resolved not in graph:
                resolved = resolved.rpartition(".")[0]
            if resolved in graph:
                visit(resolved)
        active.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
    return sorted(errors)
