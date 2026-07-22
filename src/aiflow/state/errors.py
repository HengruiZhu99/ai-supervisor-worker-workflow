class StateError(RuntimeError):
    """Base state protocol error."""


class RevisionConflict(StateError):
    """A mutation used a stale state revision."""


class LeaseConflict(StateError):
    """Another controller owns the run."""


class AmbiguousLease(LeaseConflict):
    """A cross-host lease cannot be safely taken over."""


class StateCorruption(StateError):
    """Snapshots, intents, or events disagree."""
