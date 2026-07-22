from __future__ import annotations

import hashlib
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, Mapping


def local_host_id() -> str:
    digest = hashlib.sha256(socket.gethostname().encode()).hexdigest()[:24]
    return f"host-{digest}"


def local_boot_id() -> str:
    try:
        source = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        result = subprocess.run(
            ["sysctl", "-n", "kern.boottime"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        source = result.stdout.strip() or "unknown-boot"
    return "boot-" + hashlib.sha256(source.encode()).hexdigest()[:24]


def process_start(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[21]
    except (OSError, IndexError):
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return result.stdout.strip()


def local_process_identity() -> dict[str, Any]:
    pid = os.getpid()
    return {
        "host_id": local_host_id(),
        "boot_id": local_boot_id(),
        "pid": pid,
        "process_start_time": process_start(pid),
    }


def owner_is_live(owner: Mapping[str, Any]) -> bool:
    if (
        owner.get("host_id") != local_host_id()
        or owner.get("boot_id") != local_boot_id()
    ):
        return False
    try:
        pid = int(owner["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    observed = process_start(pid)
    return bool(observed) and observed == str(owner.get("process_start_time", ""))
