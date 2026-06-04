#!/usr/bin/env python3
"""Validate worker-job progress classification before dispatch.

The gate is intentionally small and conservative.  New tasks must contain a
machine-checkable ``progress:`` block.  Older jobs may not have that block, so
history checks use the block when available and fall back to simple keyword
classification for accepted or supervisor-ready legacy jobs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_FIELDS = {
    "job_type",
    "subsystem",
    "capability_target",
    "new_executable_behavior",
    "validation_class",
    "unlocks_next",
    "metadata_only",
}
STATUS_FIELD_KEYS = {
    "progress_job_type",
    "progress_subsystem",
    "progress_validation_class",
    "progress_metadata_only",
    "progress_new_executable_behavior",
    "progress_capability_target",
    "progress_unlocks_next",
    "progress_exception_type",
    "progress_exception_record",
}

JOB_TYPES = {
    "implementation",
    "numerical_test",
    "backend_test",
    "audit",
    "metadata",
    "docs",
    "visualization",
    "planning",
}

SUBSYSTEMS = {
    "domain",
    "geometry",
    "operators",
    "gh",
    "xcts",
    "backend",
    "mpi",
    "workflow",
    "other",
}

VALIDATION_CLASSES = {
    "none",
    "schema",
    "construction",
    "identity",
    "convergence",
    "backend_matrix",
    "mpi_device",
}

METADATA_LIKE_TYPES = {"audit", "metadata", "docs", "visualization", "planning"}
EXCEPTION_TYPES = {"none", "human_approved_planning_source", "subsystem_deferred"}
METADATA_VALIDATION_CLASSES = {"none", "schema", "construction"}
HISTORY_STATES = {"accepted", "ready_for_review", "implemented"}
VAGUE_UNLOCKS = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "tbd",
    "todo",
    "unknown",
    "future",
    "future work",
    "follow-up",
    "follow up",
    "general cleanup",
    "cleanup",
}
VAGUE_UNLOCK_PATTERNS = (
    re.compile(r"\bfuture\s+work\b"),
    re.compile(r"\bfollow[- ]?up\b"),
    re.compile(r"\blater\b"),
    re.compile(r"\bgeneral\b.*\bcleanup\b"),
    re.compile(r"\btbd\b"),
    re.compile(r"\bto\s+be\s+determined\b"),
)
JOB_ID_RE = re.compile(r"^J(?P<num>\d{4,})$")


@dataclass(frozen=True)
class Progress:
    job_type: str
    subsystem: str
    capability_target: str
    new_executable_behavior: bool
    validation_class: str
    unlocks_next: str
    metadata_only: bool
    exception_type: str
    exception_record: str
    source: str

    @property
    def metadata_like(self) -> bool:
        return self.metadata_only or self.job_type in METADATA_LIKE_TYPES

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "job_type": self.job_type,
            "subsystem": self.subsystem,
            "capability_target": self.capability_target,
            "new_executable_behavior": self.new_executable_behavior,
            "validation_class": self.validation_class,
            "unlocks_next": self.unlocks_next,
            "metadata_only": self.metadata_only,
            "progress_exception_type": self.exception_type,
            "progress_exception_record": self.exception_record,
            "metadata_like": self.metadata_like,
            "source": self.source,
        }

    def status_fields(self) -> dict[str, str | bool]:
        return {
            "progress_job_type": self.job_type,
            "progress_subsystem": self.subsystem,
            "progress_validation_class": self.validation_class,
            "progress_metadata_only": self.metadata_only,
            "progress_new_executable_behavior": self.new_executable_behavior,
            "progress_capability_target": self.capability_target,
            "progress_unlocks_next": self.unlocks_next,
            "progress_exception_type": self.exception_type,
            "progress_exception_record": self.exception_record,
        }


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def parse_bool(value: str) -> bool | None:
    lowered = unquote(value).lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def extract_progress_block(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "progress:":
            continue
        base_indent = len(line) - len(line.lstrip(" "))
        block: dict[str, str] = {}
        for raw in lines[index + 1 :]:
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("```"):
                break
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= base_indent:
                break
            match = re.match(r"\s+([A-Za-z_][\w-]*):\s*(.*?)\s*$", raw)
            if match:
                block[match.group(1)] = unquote(match.group(2))
        return block
    return None


def vague_unlock(value: str) -> bool:
    lowered = unquote(value).strip().lower()
    if lowered in VAGUE_UNLOCKS:
        return True
    if len(lowered) < 12:
        return True
    return any(pattern.search(lowered) for pattern in VAGUE_UNLOCK_PATTERNS)


def progress_from_block(block: dict[str, str], source: str) -> tuple[Progress | None, list[str]]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(block))
    if missing:
        errors.append(f"{source}: missing progress fields: {', '.join(missing)}")

    job_type = block.get("job_type", "")
    subsystem = block.get("subsystem", "")
    validation_class = block.get("validation_class", "")
    new_executable = parse_bool(block.get("new_executable_behavior", ""))
    metadata_only = parse_bool(block.get("metadata_only", ""))
    exception_type = block.get("progress_exception_type", "none").strip() or "none"
    exception_record = block.get("progress_exception_record", "").strip()

    if job_type and job_type not in JOB_TYPES:
        errors.append(f"{source}: invalid job_type {job_type!r}")
    if subsystem and subsystem not in SUBSYSTEMS:
        errors.append(f"{source}: invalid subsystem {subsystem!r}")
    if validation_class and validation_class not in VALIDATION_CLASSES:
        errors.append(f"{source}: invalid validation_class {validation_class!r}")
    if block.get("new_executable_behavior") is not None and new_executable is None:
        errors.append(f"{source}: new_executable_behavior must be true or false")
    if block.get("metadata_only") is not None and metadata_only is None:
        errors.append(f"{source}: metadata_only must be true or false")
    if exception_type not in EXCEPTION_TYPES:
        errors.append(f"{source}: invalid progress_exception_type {exception_type!r}")
    if exception_type != "none" and vague_unlock(exception_record):
        errors.append(
            f"{source}: progress_exception_record is required when "
            f"progress_exception_type={exception_type!r}"
        )
    if exception_type == "none" and exception_record:
        errors.append(f"{source}: progress_exception_record requires a non-none progress_exception_type")

    capability_target = block.get("capability_target", "").strip()
    unlocks_next = block.get("unlocks_next", "").strip()
    if "capability_target" in block and vague_unlock(capability_target):
        errors.append(f"{source}: capability_target is too vague")

    metadata_like = (metadata_only is True) or job_type in METADATA_LIKE_TYPES
    if metadata_like and vague_unlock(unlocks_next):
        errors.append(
            f"{source}: metadata-like jobs require a concrete unlocks_next "
            "implementation or validation job"
        )
    if metadata_only is True and job_type in {"implementation", "numerical_test", "backend_test"}:
        errors.append(f"{source}: metadata_only=true conflicts with job_type={job_type!r}")
    if job_type == "implementation" and new_executable is False:
        errors.append(f"{source}: implementation jobs must set new_executable_behavior=true")
    if job_type == "implementation" and validation_class == "none":
        errors.append(f"{source}: implementation jobs must not use validation_class=none")
    if job_type == "numerical_test" and validation_class not in {"identity", "convergence"}:
        errors.append(f"{source}: numerical_test jobs must use validation_class identity or convergence")
    if job_type == "backend_test" and validation_class not in {"backend_matrix", "mpi_device"}:
        errors.append(f"{source}: backend_test jobs must use validation_class backend_matrix or mpi_device")
    if (
        metadata_like
        and validation_class not in METADATA_VALIDATION_CLASSES
        and exception_type == "none"
    ):
        errors.append(
            f"{source}: metadata-like jobs must use validation_class none, schema, "
            "or construction unless progress_exception_type documents the exception"
        )

    if errors:
        return None, errors

    return (
        Progress(
            job_type=job_type,
            subsystem=subsystem,
            capability_target=capability_target,
            new_executable_behavior=bool(new_executable),
            validation_class=validation_class,
            unlocks_next=unlocks_next,
            metadata_only=bool(metadata_only),
            exception_type=exception_type,
            exception_record=exception_record,
            source=source,
        ),
        [],
    )


def target_progress(task_path: Path) -> tuple[Progress | None, list[str]]:
    text = task_path.read_text(encoding="utf-8")
    block = extract_progress_block(text)
    if block is None:
        return None, [f"{task_path}: missing required progress: block"]
    return progress_from_block(block, str(task_path))


def infer_subsystem(text: str) -> str:
    lower = text.lower()
    if "workflow" in lower or "supervisor" in lower or "worker loop" in lower:
        return "workflow"
    if "xcts" in lower:
        return "xcts"
    if "generalized harmonic" in lower or re.search(r"\bgh\b", lower):
        return "gh"
    if "mpi" in lower:
        return "mpi"
    if "kokkos" in lower or "backend" in lower or "device" in lower or "gpu" in lower:
        return "backend"
    if "operator" in lower or "derivative" in lower or "interpolation" in lower:
        return "operators"
    if "jacobian" in lower or "map" in lower or "geometry" in lower:
        return "geometry"
    if "domain" in lower or "topology" in lower or "bbh" in lower or "single-bh" in lower:
        return "domain"
    return "other"


def infer_legacy_progress(job_dir: Path, status: dict[str, object]) -> Progress:
    title = str(status.get("title", ""))
    task_text = ""
    task_path = job_dir / "task.md"
    if task_path.exists():
        task_text = task_path.read_text(encoding="utf-8", errors="replace")
    haystack = f"{title}\n{task_text[:8000]}"
    lower = haystack.lower()
    subsystem = infer_subsystem(haystack)

    if any(word in lower for word in ("audit", "provenance", "literature", "source-role")):
        job_type = "audit"
    elif any(word in lower for word in ("artifact", "plot", "svg", "paraview", "visualization")):
        job_type = "visualization"
    elif any(word in lower for word in ("metadata", "manifest", "schema", "topology")):
        job_type = "metadata"
    elif any(word in lower for word in ("docs-only", "documentation-only")):
        job_type = "docs"
    else:
        job_type = "implementation"

    metadata_only = job_type in METADATA_LIKE_TYPES
    return Progress(
        job_type=job_type,
        subsystem=subsystem,
        capability_target=title or job_dir.name,
        new_executable_behavior=not metadata_only,
        validation_class="none",
        unlocks_next="legacy inferred progress classification",
        metadata_only=metadata_only,
        exception_type="none",
        exception_record="",
        source=f"{job_dir}/task.md (legacy inferred)",
    )


def job_number(job_id: str | None) -> int | None:
    if not job_id:
        return None
    match = JOB_ID_RE.match(job_id)
    if not match:
        return None
    return int(match.group("num"))


def current_job_id(task_path: Path) -> str | None:
    for parent in [task_path.parent, *task_path.parents]:
        if JOB_ID_RE.match(parent.name):
            return parent.name
    return None


def history_progress(job_dir: Path) -> Progress | None:
    status_path = job_dir / "status.json"
    if not status_path.exists():
        return None
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if status.get("state") not in HISTORY_STATES:
        return None

    task_path = job_dir / "task.md"
    if task_path.exists():
        block = extract_progress_block(task_path.read_text(encoding="utf-8", errors="replace"))
        if block is not None:
            progress, errors = progress_from_block(block, str(task_path))
            if progress is not None and not errors:
                return progress
    return infer_legacy_progress(job_dir, status)


def metadata_streak(jobs_dir: Path, target: Progress, target_job_id: str | None) -> list[Progress]:
    target_num = job_number(target_job_id)
    entries: list[tuple[int, Progress]] = []
    for job_dir in jobs_dir.glob("J*"):
        if not job_dir.is_dir():
            continue
        num = job_number(job_dir.name)
        if num is None:
            continue
        if target_num is not None and num >= target_num:
            continue
        progress = history_progress(job_dir)
        if progress is not None:
            entries.append((num, progress))

    streak: list[Progress] = []
    for _, progress in sorted(entries, reverse=True):
        if progress.subsystem != target.subsystem:
            continue
        if progress.metadata_like:
            streak.append(progress)
            continue
        break
    return streak


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path, help="task.md or proposed task file")
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=Path(".ai/jobs"),
        help="job history directory, default: .ai/jobs",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable gate result")
    return parser.parse_args(argv)


def result_payload(progress: Progress | None, errors: list[str]) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": not errors,
        "errors": errors,
        "progress": progress.to_dict() if progress is not None else None,
        "status_fields": progress.status_fields() if progress is not None and not errors else {},
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    task_path = args.task
    jobs_dir = args.jobs_dir

    if not task_path.exists():
        print(f"progress gate: task file does not exist: {task_path}", file=sys.stderr)
        return 2

    progress, errors = target_progress(task_path)
    if progress is not None and progress.metadata_like:
        streak = metadata_streak(jobs_dir, progress, current_job_id(task_path))
        if len(streak) >= 2:
            errors.append(
                "metadata-like streak limit exceeded for subsystem "
                f"{progress.subsystem!r}: found {len(streak)} prior metadata-like "
                "accepted/supervisor-ready jobs. Dispatch implementation, "
                "numerical_test, backend_test, open a human decision gate, or defer "
                "the subsystem instead."
            )

    if args.json:
        print(json.dumps(result_payload(progress, errors), indent=2, sort_keys=True))
        return 1 if errors else 0

    if errors:
        print("progress gate: failed")
        for error in errors:
            print(f"- {error}")
        return 1

    assert progress is not None
    print(
        "progress gate: passed "
        f"job_type={progress.job_type} subsystem={progress.subsystem} "
        f"metadata_only={str(progress.metadata_only).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
