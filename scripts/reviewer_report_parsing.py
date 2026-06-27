#!/usr/bin/env python3
"""Shared, robust parsing of reviewer-report machine blocks.

A reviewer report must contain one fenced ```yaml block with the `diff_coverage`,
`review_decision`, and `progress_review` sections. In practice reports can also
contain:

* an echoed copy of the reviewer *prompt template* (placeholder paths such as
  ``path/from/changed_files``), and
* tokenized / garbled transcript fragments emitted before the real block.

Historically these broke the two separate ad-hoc parsers in
``check_reviewer_coverage.py`` and ``analyze_reviewer_reports.py`` in different
ways (workflow_improvement_queue WFI-0001/WFI-0002: a malformed fragment before
the final valid block failed an otherwise-complete review). This module is the
single source of truth for both: it selects the LAST valid machine block,
ignores the echoed template, and parses scalars/lists/sections tolerantly with
the Python standard library only (no third-party YAML dependency).
"""

from __future__ import annotations

import re

# Placeholder values copied verbatim from the reviewer prompt template. A block
# that still contains any of these is the echoed instruction template, not a real
# review, and must never be selected as the machine block.
TEMPLATE_SENTINELS = (
    "path/from/changed_files",
)


def fenced_blocks(text: str) -> list[str]:
    """Return the contents of every fenced ```yaml/```yml/``` block, in order."""
    return re.findall(r"```(?:yaml|yml)?\s*\n(.*?)```", text, re.S | re.I)


def is_template_block(block: str) -> bool:
    """True if the block is the echoed reviewer prompt template, not a review."""
    return any(sentinel in block for sentinel in TEMPLATE_SENTINELS)


def count_machine_blocks(text: str, require_key: str) -> int:
    """Number of non-template fenced blocks that contain ``require_key``."""
    return sum(
        1
        for block in fenced_blocks(text)
        if require_key in block and not is_template_block(block)
    )


def select_machine_block(text: str, require_key: str) -> str:
    """Return the LAST valid machine block containing ``require_key``.

    Preference order:
      1. the last fenced block that contains ``require_key`` and is not the
         echoed template (robust to earlier tokenized/malformed fragments);
      2. the text following the last bare ``require_key`` marker (legacy
         unfenced reports), truncated at a following fence, if it is not the
         echoed template;
      3. an empty string when no usable block exists.
    """
    for block in reversed(fenced_blocks(text)):
        if require_key in block and not is_template_block(block):
            return block
    marker = text.rfind(require_key)
    if marker >= 0:
        region = text[marker:]
        fence = region.find("```")
        if fence >= 0:
            region = region[:fence]
        if not is_template_block(region):
            return region
    return ""


def parse_bool(raw: str) -> bool:
    return raw.strip().lower().strip("'\"") in {"true", "yes", "1"}


def parse_scalar(block: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", block, re.M)
    return match.group(1).strip().strip("'\"") if match else ""


def parse_list(block: str, key: str) -> list[str]:
    """Parse a YAML-style ``key:`` list, tolerating ``key: []`` and indented items."""
    if re.search(rf"^\s*{re.escape(key)}\s*:\s*\[\s*\]\s*$", block, re.M):
        return []
    lines = block.splitlines()
    values: list[str] = []
    in_list = False
    base_indent = 0
    for line in lines:
        match = re.match(rf"^(\s*){re.escape(key)}\s*:\s*$", line)
        if match:
            in_list = True
            base_indent = len(match.group(1))
            continue
        if in_list:
            stripped = line.strip()
            if stripped.startswith("- "):
                values.append(stripped[2:].strip().strip("'\""))
                continue
            if stripped and len(line) - len(line.lstrip()) <= base_indent:
                break
    return values


def section_block(block: str, section: str) -> str:
    """Return the indented body of ``section:`` within a machine block."""
    lines = block.splitlines()
    for index, line in enumerate(lines):
        match = re.match(rf"^(\s*){re.escape(section)}\s*:\s*(?:#.*)?$", line)
        if not match:
            continue
        base_indent = len(match.group(1))
        selected: list[str] = []
        for raw in lines[index + 1 :]:
            stripped = raw.strip()
            if not stripped:
                selected.append(raw)
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= base_indent and re.match(r"^[A-Za-z_][\w-]*\s*:", stripped):
                break
            selected.append(raw)
        return "\n".join(selected)
    return ""


def parse_scalar_in_section(block: str, section: str, key: str) -> str:
    scoped = section_block(block, section)
    return parse_scalar(scoped, key) if scoped else ""


def parse_list_in_section(block: str, section: str, key: str) -> list[str]:
    scoped = section_block(block, section)
    return parse_list(scoped, key) if scoped else []
