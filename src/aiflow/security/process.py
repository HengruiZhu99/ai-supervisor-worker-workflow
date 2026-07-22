from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from aiflow.security.environment import scrub_environment


def run_owned_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    injected: Mapping[str, str] | None = None,
    timeout: float,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one bounded subprocess in an owned process group and reap it on timeout."""
    if timeout <= 0:
        raise ValueError("owned process timeout must be finite and positive")
    root = cwd.resolve()
    process = subprocess.Popen(
        [str(part) for part in command],
        cwd=root,
        env=scrub_environment(env, injected=injected),
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(list(command), 124, stdout, stderr)
    return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)
