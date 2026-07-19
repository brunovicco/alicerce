"""Provider-neutral persistence boundary for trusted run state."""

from enum import StrEnum
from typing import Protocol

from alicerce.domain.lifecycle import LifecycleTransition
from alicerce.domain.run_identity import RunId
from alicerce.domain.state import RunCheckpoint, StateUpdate


class StateStoreErrorCause(StrEnum):
    """Stable operational causes exposed by state-store implementations."""

    ALREADY_EXISTS = "already_exists"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"


class StateStoreError(RuntimeError):
    """Raised when a state-store operation cannot honor its contract."""

    def __init__(self, cause: StateStoreErrorCause, detail: str) -> None:
        """Record a stable typed cause."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


class StateStorePort(Protocol):
    """Exclusive initialization, CAS updates, and append-only history."""

    def initialize(self, checkpoint: RunCheckpoint) -> None:
        """Persist the identity-derived initial checkpoint exclusively."""
        ...

    def load(self, run_id: RunId) -> RunCheckpoint | None:
        """Return the current checkpoint, or ``None`` when it is absent."""
        ...

    def compare_and_append(self, update: StateUpdate) -> RunCheckpoint:
        """Append the event only when the stored checkpoint equals expected."""
        ...

    def history(self, run_id: RunId) -> tuple[LifecycleTransition, ...]:
        """Return accepted transitions in revision order."""
        ...
