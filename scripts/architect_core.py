#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Pure, dependency-free logic for the Architect intake stage.

The Architect interviews a user, builds a structured project specification, and
compiles it into the bootstrap artifacts the existing supervisor consumes
(`design_prompt.md`, `project_brief.md`, `roadmap.md`, `ledger.md`,
`autonomy_delegation.json`). This module owns the parts that must be
deterministic and unit-testable in isolation from any agent process:

* the spec data model (requirements, acceptance criteria, milestones with an
  executable Definition-of-Done, risks, glossary),
* merging the per-turn machine block the interview agent emits,
* the completeness predicate that gates handoff, and
* rendering the spec into the supervisor bootstrap files.

It performs no I/O beyond what it is handed and uses only the Python standard
library (no third-party YAML), mirroring `consensus_core.py`.

Per-turn interview contract: the agent emits exactly one fenced ```json block::

    ```json
    {
      "ask_user": "the next question(s) to show the user",
      "spec_updates": { ...partial spec fields to merge... },
      "open_questions": ["unresolved items blocking completeness"],
      "ready_to_finalize": false
    }
    ```
"""

from __future__ import annotations

import json
import re

# ----------------------------------------------------------------------------
# Spec model
# ----------------------------------------------------------------------------

PRIORITIES = ("must", "should", "could", "wont")
REQ_KINDS = ("functional", "non_functional")

# Stable id prefixes.
REQ_PREFIX = "R"
ACC_PREFIX = "A"
MILESTONE_PREFIX = "M"


def new_spec() -> dict:
    """Return an empty, canonical spec document."""
    return {
        "project": {
            "name": "",
            "language": "",
            "summary": "",
            "description": "",
            "target_users": "",
        },
        "requirements": [],   # {id, text, priority, kind, acceptance: [acc_id,...]}
        "acceptance": [],     # {id, requirement, statement, test_command, executable}
        "milestones": [],     # {id, title, summary, requirements, definition_of_done, depends_on}
        "constraints": [],
        "out_of_scope": [],
        "risks": [],          # {risk, mitigation} or str
        "glossary": [],       # {term, definition}
        "success_metrics": [],
        "runtime": {"build": "", "test": "", "lint": "", "format_check": ""},
        "budgets": {
            "max_attempts_per_job": 8,
            "max_tokens_per_milestone": 0,
            "max_wallclock_per_milestone": 0,
        },
        "open_questions": [],
    }


def _upsert_by_id(existing: list[dict], incoming: list) -> list[dict]:
    """Upsert objects by their ``id`` field, preserving order, appending new ids."""
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for item in existing:
        if isinstance(item, dict) and item.get("id"):
            by_id[item["id"]] = dict(item)
            order.append(item["id"])
    for item in incoming:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not item_id:
            continue
        if item_id in by_id:
            by_id[item_id].update(item)
        else:
            by_id[item_id] = dict(item)
            order.append(item_id)
    return [by_id[i] for i in order]


# Fields merged as object lists keyed by id, vs. replaced wholesale, vs. dict-merged.
_OBJECT_LIST_FIELDS = ("requirements", "acceptance", "milestones")
_REPLACE_LIST_FIELDS = ("constraints", "out_of_scope", "risks", "glossary", "success_metrics")
_DICT_FIELDS = ("project", "runtime", "budgets")


def apply_update(spec: dict, update: dict) -> dict:
    """Merge an agent ``architect_update`` into ``spec`` in place and return it.

    Merge semantics:
      * ``project``/``runtime``/``budgets``: shallow dict merge.
      * ``requirements``/``acceptance``/``milestones``: upsert by ``id``.
      * other lists: replaced when present (agent sends the full current list).
      * ``open_questions``: replaced when present.
    """
    if not isinstance(update, dict):
        return spec
    spec_updates = update.get("spec_updates")
    if isinstance(spec_updates, dict):
        for field in _DICT_FIELDS:
            value = spec_updates.get(field)
            if isinstance(value, dict):
                spec.setdefault(field, {}).update({k: v for k, v in value.items()})
        for field in _OBJECT_LIST_FIELDS:
            value = spec_updates.get(field)
            if isinstance(value, list):
                spec[field] = _upsert_by_id(spec.get(field, []), value)
        for field in _REPLACE_LIST_FIELDS:
            value = spec_updates.get(field)
            if isinstance(value, list):
                spec[field] = value
    if "open_questions" in update and isinstance(update["open_questions"], list):
        spec["open_questions"] = [str(q) for q in update["open_questions"] if str(q).strip()]
    return spec


def extract_architect_update(text: str) -> dict | None:
    """Return the last parseable fenced ```json architect_update block, or None."""
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S | re.I)
    for block in reversed(blocks):
        block = block.strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and (
            "spec_updates" in data or "ask_user" in data or "ready_to_finalize" in data
        ):
            return data
    return None


# ----------------------------------------------------------------------------
# Completeness
# ----------------------------------------------------------------------------

def _acceptance_ids(spec: dict) -> set[str]:
    return {a["id"] for a in spec.get("acceptance", []) if isinstance(a, dict) and a.get("id")}


def acceptance_for_requirement(spec: dict, req_id: str) -> list[dict]:
    return [
        a
        for a in spec.get("acceptance", [])
        if isinstance(a, dict) and a.get("requirement") == req_id
    ]


def spec_completeness(spec: dict) -> dict:
    """Assess whether the spec is complete enough to hand off to the supervisor.

    Returns ``{"complete": bool, "missing": [...], "warnings": [...]}``. ``missing``
    items block handoff; ``warnings`` do not.
    """
    missing: list[str] = []
    warnings: list[str] = []

    project = spec.get("project", {})
    for key in ("name", "language", "summary"):
        if not str(project.get(key, "")).strip():
            missing.append(f"project.{key} is empty")

    requirements = spec.get("requirements", [])
    if not requirements:
        missing.append("no requirements captured")

    acc_ids = _acceptance_ids(spec)
    for req in requirements:
        if not isinstance(req, dict) or not req.get("id"):
            missing.append("a requirement is missing an id")
            continue
        linked = acceptance_for_requirement(spec, req["id"])
        declared = [a for a in (req.get("acceptance") or []) if a in acc_ids]
        if not linked and not declared:
            missing.append(f"requirement {req['id']} has no acceptance criterion")
        if str(req.get("priority", "")).lower() not in PRIORITIES:
            warnings.append(f"requirement {req['id']} has no MoSCoW priority")

    milestones = spec.get("milestones", [])
    if not milestones:
        missing.append("no milestones defined")

    covered_reqs: set[str] = set()
    for milestone in milestones:
        if not isinstance(milestone, dict) or not milestone.get("id"):
            missing.append("a milestone is missing an id")
            continue
        dod = milestone.get("definition_of_done") or []
        if not dod:
            missing.append(f"milestone {milestone['id']} has no Definition-of-Done")
        for entry in dod:
            if not isinstance(entry, dict):
                missing.append(f"milestone {milestone['id']} DoD entry is malformed")
                continue
            acc = entry.get("acceptance")
            if acc and acc not in acc_ids:
                missing.append(
                    f"milestone {milestone['id']} DoD references unknown acceptance {acc}"
                )
            if not str(entry.get("check", "")).strip() and not acc:
                missing.append(f"milestone {milestone['id']} DoD entry has no acceptance or check")
        for req_id in milestone.get("requirements", []) or []:
            covered_reqs.add(req_id)

    for req in requirements:
        if isinstance(req, dict) and req.get("id") and req["id"] not in covered_reqs:
            missing.append(f"requirement {req['id']} is not covered by any milestone")

    if not str(spec.get("runtime", {}).get("test", "")).strip():
        missing.append("runtime.test command is not set (needed to prove Definition-of-Done)")

    open_questions = [q for q in spec.get("open_questions", []) if str(q).strip()]
    if open_questions:
        missing.append(f"{len(open_questions)} open question(s) remain unresolved")

    if not spec.get("risks"):
        warnings.append("no risks recorded")
    if not any(
        isinstance(r, dict) and str(r.get("kind", "")).lower() == "non_functional"
        for r in requirements
    ):
        warnings.append("no non-functional requirements recorded")
    for acc in spec.get("acceptance", []):
        if isinstance(acc, dict) and not str(acc.get("test_command", "")).strip():
            warnings.append(f"acceptance {acc.get('id')} has no executable test_command")

    return {"complete": not missing, "missing": missing, "warnings": warnings}


# ----------------------------------------------------------------------------
# Minimal dependency-free YAML for project.yaml (nested maps + scalars only)
# ----------------------------------------------------------------------------

def _coerce_scalar(value: str):
    text = value.strip()
    if text == "" or text in {"~", "null"}:
        return ""
    if (text[0], text[-1]) in {('"', '"'), ("'", "'")} and len(text) >= 2:
        return text[1:-1]
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def parse_simple_yaml(text: str) -> dict:
    """Parse a restricted YAML subset: nested maps (2-space indent) and scalars.

    Sufficient for project.yaml, which contains only nested maps and scalar
    leaves (no lists). Comments (``#``) and blank lines are ignored.
    """
    root: dict = {}
    # Stack of (indent, container) frames.
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key_part, sep, value_part = line.strip().partition(":")
        if not sep:
            continue
        key = key_part.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        container = stack[-1][1]
        if value_part.strip() == "":
            child: dict = {}
            container[key] = child
            stack.append((indent, child))
        else:
            container[key] = _coerce_scalar(value_part)
    return root


def _dump_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    if re.search(r"[:#]", text) or text != text.strip():
        return json.dumps(text)
    return text


def dump_simple_yaml(obj: dict, indent: int = 0) -> str:
    """Serialize a nested map/scalar structure to the restricted YAML subset."""
    lines: list[str] = []
    pad = "  " * indent
    for key, value in obj.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            if value:
                lines.append(dump_simple_yaml(value, indent + 1).rstrip("\n"))
        else:
            lines.append(f"{pad}{key}: {_dump_value(value)}")
    return "\n".join(lines) + ("\n" if indent == 0 else "")


# ----------------------------------------------------------------------------
# project.yaml
# ----------------------------------------------------------------------------

def default_project_yaml(spec: dict | None = None) -> dict:
    """Build the stack-agnostic project.yaml structure from a spec."""
    spec = spec or new_spec()
    project = spec.get("project", {})
    runtime = spec.get("runtime", {})
    budgets = spec.get("budgets", {})
    return {
        "project": {
            "name": project.get("name", "") or "untitled-project",
            "language": project.get("language", "") or "python",
            "description": project.get("summary", ""),
        },
        "runtime": {
            "build": runtime.get("build", ""),
            "test": runtime.get("test", ""),
            "lint": runtime.get("lint", ""),
            "format_check": runtime.get("format_check", ""),
        },
        "agents": {
            "worker_wrapper": "cursor-agent",
            "worker_model": "claude-fable-5-thinking-high",
            "reviewer_panel": "reviewer",
            "supervisor_panel": "supervisor",
        },
        "consensus": {
            "reviewer_enabled": True,
            "reviewer_quorum": "unanimous",
            "reviewer_max_rounds": 3,
            "supervisor_enabled": True,
            "supervisor_quorum": "unanimous",
            "supervisor_max_rounds": 3,
        },
        "budgets": {
            "max_attempts_per_job": budgets.get("max_attempts_per_job", 8),
            "max_tokens_per_milestone": budgets.get("max_tokens_per_milestone", 0),
            "max_wallclock_per_milestone": budgets.get("max_wallclock_per_milestone", 0),
        },
    }


# ----------------------------------------------------------------------------
# Rendering: .ai/architect/ spec artifacts
# ----------------------------------------------------------------------------

def render_requirements_md(spec: dict) -> str:
    lines = ["# Requirements", ""]
    for kind, label in (("functional", "Functional"), ("non_functional", "Non-functional")):
        reqs = [r for r in spec.get("requirements", []) if str(r.get("kind", "functional")) == kind]
        if not reqs:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for req in reqs:
            priority = str(req.get("priority", "")).upper()
            accs = acceptance_for_requirement(spec, req.get("id", ""))
            acc_ids = ", ".join(a.get("id", "") for a in accs) or "(none)"
            lines.append(f"- **{req.get('id')}** [{priority}] {req.get('text', '')}  (acceptance: {acc_ids})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_acceptance_md(spec: dict) -> str:
    lines = ["# Acceptance Criteria", ""]
    for acc in spec.get("acceptance", []):
        cmd = acc.get("test_command", "")
        lines.append(f"## {acc.get('id')} (requirement {acc.get('requirement', '?')})")
        lines.append("")
        lines.append(acc.get("statement", ""))
        if cmd:
            lines.append("")
            lines.append("```bash")
            lines.append(cmd)
            lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_milestones_md(spec: dict) -> str:
    lines = ["# Milestones", ""]
    for milestone in spec.get("milestones", []):
        lines.append(f"## {milestone.get('id')}: {milestone.get('title', '')}")
        lines.append("")
        if milestone.get("summary"):
            lines.append(milestone["summary"])
            lines.append("")
        reqs = ", ".join(milestone.get("requirements", []) or []) or "(none)"
        lines.append(f"Requirements: {reqs}")
        depends = ", ".join(milestone.get("depends_on", []) or [])
        if depends:
            lines.append(f"Depends on: {depends}")
        lines.append("")
        lines.append("Definition of Done:")
        for entry in milestone.get("definition_of_done", []) or []:
            acc = entry.get("acceptance", "")
            check = entry.get("check", "")
            lines.append(f"- [{acc}] {check}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_risks_md(spec: dict) -> str:
    lines = ["# Risks", ""]
    for risk in spec.get("risks", []):
        if isinstance(risk, dict):
            lines.append(f"- {risk.get('risk', '')} -- mitigation: {risk.get('mitigation', 'TBD')}")
        else:
            lines.append(f"- {risk}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_glossary_md(spec: dict) -> str:
    lines = ["# Glossary", ""]
    for item in spec.get("glossary", []):
        if isinstance(item, dict):
            lines.append(f"- **{item.get('term', '')}**: {item.get('definition', '')}")
        else:
            lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------------------
# Rendering: supervisor bootstrap artifacts
# ----------------------------------------------------------------------------

def render_design_prompt(spec: dict) -> str:
    project = spec.get("project", {})
    lines = ["# Detailed Design Prompt", ""]
    lines.append(
        "This file is the authoritative project specification, compiled by the "
        "Architect intake stage. The supervisor extracts milestones and acceptance "
        "criteria from it and dispatches small worker jobs; it includes only the "
        "relevant subset in each worker task."
    )
    lines.append("")
    lines.append(f"## Project: {project.get('name', '')}")
    lines.append("")
    lines.append(f"Language/stack: {project.get('language', '')}")
    lines.append("")
    lines.append(project.get("summary", ""))
    if project.get("description"):
        lines.append("")
        lines.append(project["description"])
    if project.get("target_users"):
        lines.append("")
        lines.append(f"Target users: {project['target_users']}")
    lines.append("")
    lines.append("## Requirements")
    lines.append("")
    lines.append(render_requirements_md(spec).split("\n", 2)[-1].rstrip())
    if spec.get("constraints"):
        lines.append("")
        lines.append("## Constraints")
        lines.append("")
        for c in spec["constraints"]:
            lines.append(f"- {c}")
    if spec.get("out_of_scope"):
        lines.append("")
        lines.append("## Out of scope")
        lines.append("")
        for c in spec["out_of_scope"]:
            lines.append(f"- {c}")
    lines.append("")
    lines.append("## Milestones and Definition of Done")
    lines.append("")
    lines.append(render_milestones_md(spec).split("\n", 2)[-1].rstrip())
    return "\n".join(lines).rstrip() + "\n"


def render_project_brief(spec: dict) -> str:
    project = spec.get("project", {})
    milestones = spec.get("milestones", [])
    lines = ["# Project Brief", ""]
    lines.append(f"- Name: {project.get('name', '')}")
    lines.append(f"- Language/stack: {project.get('language', '')}")
    lines.append(f"- Summary: {project.get('summary', '')}")
    lines.append(f"- Milestones: {len(milestones)}")
    lines.append(f"- Requirements: {len(spec.get('requirements', []))}")
    lines.append("")
    lines.append("## Current status")
    lines.append("")
    lines.append("Spec compiled by the Architect intake stage; awaiting first worker job.")
    lines.append("")
    lines.append("## Milestone overview")
    lines.append("")
    for milestone in milestones:
        lines.append(f"- {milestone.get('id')}: {milestone.get('title', '')}")
    return "\n".join(lines).rstrip() + "\n"


def milestone_dod_block(milestone: dict) -> str:
    """Machine-readable Definition-of-Done block for a milestone (used by roadmap)."""
    lines = ["```yaml", "definition_of_done:", f"  milestone: {milestone.get('id')}", "  criteria:"]
    for entry in milestone.get("definition_of_done", []) or []:
        lines.append(f"    - acceptance: {entry.get('acceptance', '')}")
        check = entry.get("check", "")
        if check:
            lines.append(f"      check: {json.dumps(check)}")
    lines.append("```")
    return "\n".join(lines)


def render_roadmap(spec: dict) -> str:
    lines = ["# Roadmap", ""]
    lines.append(
        "Milestones below carry a machine-readable Definition-of-Done. Milestone "
        "closure is gated on the named acceptance checks passing, not on agent "
        "self-report."
    )
    lines.append("")
    for milestone in spec.get("milestones", []):
        lines.append(f"## {milestone.get('id')}: {milestone.get('title', '')}")
        lines.append("")
        if milestone.get("summary"):
            lines.append(milestone["summary"])
            lines.append("")
        reqs = ", ".join(milestone.get("requirements", []) or []) or "(none)"
        lines.append(f"Requirements covered: {reqs}")
        lines.append("")
        lines.append(milestone_dod_block(milestone))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_ledger_seed(spec: dict) -> str:
    project = spec.get("project", {})
    lines = ["# Ledger", ""]
    lines.append(
        f"- Project `{project.get('name', '')}` initialized by the Architect intake stage."
    )
    lines.append("- Spec compiled; bootstrap artifacts generated; awaiting first worker job.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


DEFAULT_EXCEPTION_TRIGGERS = [
    "scope expansion beyond the delegated milestone text",
    "a new or ambiguous requirement, interface, or design decision not covered by the spec",
    "an acceptance criterion cannot be satisfied as written and needs renegotiation",
    "three failed worker attempts for the same root cause after supervisor task refinement",
    "a reviewer/consensus panel blocks acceptance and the supervisor cannot justify waiving it",
    "a budget (attempts, tokens, or wall-clock) for a job or milestone is exceeded",
    "main worktree or workflow state cannot be made clean without destructive cleanup",
]


def build_autonomy_delegation(spec: dict, delegate_milestones: int = 1) -> dict:
    """Seed autonomy_delegation.json: delegate the first milestone(s), gate the rest."""
    milestones = [m for m in spec.get("milestones", []) if isinstance(m, dict) and m.get("id")]
    delegated = [m["id"] for m in milestones[:delegate_milestones]]
    review_before = [m["id"] for m in milestones[delegate_milestones:delegate_milestones + 1]]
    entry = milestones[0]["id"] if milestones else ""
    project = spec.get("project", {})
    return {
        "schema_version": 1,
        "active": True,
        "approved_by": "architect_intake",
        "summary": (
            f"Architect-compiled delegation for project {project.get('name', '')}: "
            f"delegate milestone(s) {', '.join(delegated) or '(none)'} and require human "
            f"review before {', '.join(review_before) or '(no further milestone)'}"
        ),
        "current_tranche": {
            "id": "architect_initial_tranche",
            "description": (
                "Initial autonomous tranche compiled from the Architect spec. The "
                "supervisor may implement and validate the delegated milestone(s) "
                "until their Definition-of-Done acceptance checks pass."
            ),
            "entry_milestone": entry,
            "delegated_milestones": delegated,
            "review_required_before": review_before,
            "allowed_scope": [
                f"implement and validate milestone {mid} per its Definition-of-Done"
                for mid in delegated
            ],
            "forbidden_scope": [
                "work on milestones beyond the delegated set before the human boundary",
                "closing a milestone without its Definition-of-Done acceptance checks passing",
            ],
        },
        "future_human_boundaries": [
            {
                "before_milestone": mid,
                "name": f"{mid}_boundary",
                "reason": "Review accepted evidence before starting the next milestone.",
            }
            for mid in review_before
        ],
        "exception_triggers": DEFAULT_EXCEPTION_TRIGGERS,
        "closure_record_policy": {
            "intermediate_milestone_record_required": True,
            "human_gate_required_for_delegated_intermediate_milestones": False,
            "required_record_locations": [
                ".ai/supervisor/ledger.md",
                ".ai/supervisor/project_brief.md",
                ".ai/supervisor/roadmap.md",
            ],
            "record_must_include": [
                "accepted jobs and commits",
                "acceptance checks passed for the milestone Definition-of-Done",
                "remaining exclusions",
                "next small worker job",
                "explicit statement that the closure remains inside the delegated boundary",
            ],
        },
    }


# ----------------------------------------------------------------------------
# Interview prompt construction
# ----------------------------------------------------------------------------

ELICITATION_PROTOCOL = """\
You are the Architect: an intake agent that interviews a user to produce a
complete, buildable specification for a NEW software project before any code is
written. Your job is to ask focused questions until the spec is complete, then
signal readiness to finalize.

Cover, in roughly this order, but adapt to the user:
1. Project name, one-line summary, the problem it solves, and target users.
2. Language/stack and how it is built/tested/linted (the runtime commands).
3. Functional requirements (each with a MoSCoW priority: must/should/could/wont).
4. Non-functional requirements (performance, portability, security, etc.).
5. For EACH requirement, at least one acceptance criterion. Prefer an executable
   acceptance criterion: a concrete test command that proves it.
6. Constraints and explicit out-of-scope items.
7. Milestones that sequence the work. EACH milestone must have a Definition of
   Done that references acceptance-criterion ids and the check that proves them.
   Every requirement must be covered by at least one milestone.
8. Risks (with mitigations) and a short glossary of domain terms.

Rules:
- Ask only what is still missing or ambiguous. Be concise. Batch related
  questions. Do not pad.
- Never invent requirements the user did not ask for; confirm assumptions.
- Keep ids stable: requirements R-001..., acceptance A-001..., milestones M1....
- Do not declare readiness until every requirement has an acceptance criterion,
  every milestone has a Definition of Done, every requirement is covered by a
  milestone, the runtime test command is known, and no open questions remain.

Every turn, after any prose, emit EXACTLY ONE fenced json block of the form:

```json
{
  "ask_user": "the next question(s) to show the user (empty when finalizing)",
  "spec_updates": {
    "project": {"name": "...", "language": "...", "summary": "...", "target_users": "..."},
    "runtime": {"build": "...", "test": "...", "lint": "...", "format_check": "..."},
    "requirements": [{"id": "R-001", "text": "...", "priority": "must", "kind": "functional"}],
    "acceptance": [{"id": "A-001", "requirement": "R-001", "statement": "...", "test_command": "...", "executable": true}],
    "milestones": [{"id": "M1", "title": "...", "summary": "...", "requirements": ["R-001"], "definition_of_done": [{"acceptance": "A-001", "check": "..."}], "depends_on": []}],
    "constraints": ["..."],
    "out_of_scope": ["..."],
    "risks": [{"risk": "...", "mitigation": "..."}],
    "glossary": [{"term": "...", "definition": "..."}]
  },
  "open_questions": ["unresolved items that still block completeness"],
  "ready_to_finalize": false
}
```

Only include the spec_updates fields that changed this turn. Send the FULL list
for constraints/out_of_scope/risks/glossary (they are replaced wholesale); send
only changed/added items for requirements/acceptance/milestones (merged by id).
Set ready_to_finalize true only when the spec is complete by the rules above.
"""


def render_spec_summary(spec: dict) -> str:
    """A compact human/agent-readable snapshot of the current spec state."""
    completeness = spec_completeness(spec)
    project = spec.get("project", {})
    lines = ["## Current spec state", ""]
    lines.append(f"- name: {project.get('name', '') or '(unset)'}")
    lines.append(f"- language: {project.get('language', '') or '(unset)'}")
    lines.append(f"- summary: {project.get('summary', '') or '(unset)'}")
    lines.append(f"- runtime.test: {spec.get('runtime', {}).get('test', '') or '(unset)'}")
    lines.append(f"- requirements: {len(spec.get('requirements', []))}")
    lines.append(f"- acceptance: {len(spec.get('acceptance', []))}")
    lines.append(f"- milestones: {len(spec.get('milestones', []))}")
    lines.append(f"- complete: {completeness['complete']}")
    if completeness["missing"]:
        lines.append("- still missing:")
        for item in completeness["missing"]:
            lines.append(f"  - {item}")
    if spec.get("open_questions"):
        lines.append("- open questions:")
        for q in spec["open_questions"]:
            lines.append(f"  - {q}")
    return "\n".join(lines)


def build_interview_prompt(spec: dict, history: list[dict], user_message: str) -> str:
    """Assemble the per-turn interview prompt (system protocol + state + transcript)."""
    parts = [ELICITATION_PROTOCOL, "", render_spec_summary(spec), ""]
    if history:
        parts.append("## Conversation so far")
        parts.append("")
        for turn in history[-12:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            parts.append(f"{role}: {content}")
        parts.append("")
    parts.append("## Latest user message")
    parts.append("")
    parts.append(user_message or "(the user has not said anything yet; greet them and begin the interview)")
    parts.append("")
    parts.append("Respond now: ask the next questions and emit the architect_update json block.")
    return "\n".join(parts)
