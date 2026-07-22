from __future__ import annotations


class ProfileError(ValueError):
    pass


PROFILE_ADDITIONS: dict[str, tuple[str, ...]] = {
    "solo": ("tdd-solo", "systematic-debugging", "verification-before-completion"),
    "science": (
        "numerical-test-design",
        "scientific-code-review",
        "paper-equation-implementation",
        "experiment-provenance",
        "performance-portability-review",
    ),
    "hpc": ("hpc-job-monitor", "hpc-job-triage", "cluster-portability"),
    "orchestrated": ("grill-me-nr", "tdd-nr", "handoff-nr", "aiflow-autonomous"),
    "full": ("experiment-sweep", "gui-ux-audit", "release-readiness"),
}


def profile_skills(profile: str) -> tuple[str, ...]:
    if profile not in PROFILE_ADDITIONS:
        raise ProfileError(f"unknown project profile: {profile}")
    parents = {
        "solo": (),
        "science": ("solo",),
        "hpc": ("science",),
        "orchestrated": ("science",),
        "full": ("hpc", "orchestrated"),
    }
    result: list[str] = []
    for parent in parents[profile]:
        result.extend(profile_skills(parent))
    result.extend(PROFILE_ADDITIONS[profile])
    return tuple(dict.fromkeys(result))
