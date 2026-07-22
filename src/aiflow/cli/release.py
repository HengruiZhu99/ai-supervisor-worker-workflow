from __future__ import annotations

import json
from pathlib import Path

from aiflow.release.artifact import build_artifact, verify_artifact


def package_command(args) -> int:
    if args.package_action == "build":
        result = build_artifact(Path(args.distribution_root), Path(args.output_dir))
    else:
        result = verify_artifact(Path(args.artifact))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) else 6
