"""Immutable checkpoints and validated state updates for trusted runs."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from alicerce.domain.contracts import FinalState
from alicerce.domain.lifecycle import (
    LifecycleActor,
    LifecycleAdvance,
    LifecycleState,
    RunLifecycle,
    advance_lifecycle,
    start_lifecycle,
)
from alicerce.domain.run_identity import RunIdentity


class StateInvariantCause(StrEnum):
    """Typed causes for rejected checkpoints and state updates."""

    RUN_MISMATCH = "run_mismatch"
    TIME_REGRESSION = "time_regression"
    REVISION_MISMATCH = "revision_mismatch"
    STATE_MISMATCH = "state_mismatch"
    EVENT_MISMATCH = "event_mismatch"


class StateInvariantError(ValueError):
    """Raised when immutable state components do not describe one history."""

    def __init__(self, cause: StateInvariantCause, detail: str) -> None:
        """Record a stable typed cause."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    """Immutable identity and current lifecycle snapshot for one run."""

    identity: RunIdentity
    lifecycle: RunLifecycle

    def __post_init__(self) -> None:
        """Bind the snapshot to the same run and a non-regressing time."""
        identity = _require_instance(self.identity, name="identity", expected=RunIdentity)
        lifecycle = _require_instance(
            self.lifecycle,
            name="lifecycle",
            expected=RunLifecycle,
        )
        if identity.run_id != lifecycle.run_id:
            raise StateInvariantError(
                StateInvariantCause.RUN_MISMATCH,
                "identity and lifecycle must reference the same run",
            )
        if lifecycle.updated_at < identity.created_at:
            raise StateInvariantError(
                StateInvariantCause.TIME_REGRESSION,
                "lifecycle time cannot precede identity creation",
            )


@dataclass(frozen=True, slots=True)
class StateUpdate:
    """One CAS precondition and the lifecycle advance to append."""

    expected: RunCheckpoint
    advance: LifecycleAdvance

    def __post_init__(self) -> None:
        """Ensure the expected snapshot, event, and result form one update."""
        expected = _require_instance(
            self.expected,
            name="expected",
            expected=RunCheckpoint,
        )
        advance = _require_instance(
            self.advance,
            name="advance",
            expected=LifecycleAdvance,
        )
        current = expected.lifecycle
        updated = advance.lifecycle
        event = advance.transition

        if current.run_id != updated.run_id or current.run_id != event.run_id:
            raise StateInvariantError(
                StateInvariantCause.RUN_MISMATCH,
                "expected snapshot, event, and result must reference the same run",
            )
        if updated.revision != current.revision + 1 or event.revision != updated.revision:
            raise StateInvariantError(
                StateInvariantCause.REVISION_MISMATCH,
                "state update must advance exactly one revision",
            )
        if event.from_state is not current.state or event.to_state is not updated.state:
            raise StateInvariantError(
                StateInvariantCause.STATE_MISMATCH,
                "event states must connect the expected and resulting snapshots",
            )
        if event.occurred_at < current.updated_at:
            raise StateInvariantError(
                StateInvariantCause.TIME_REGRESSION,
                "event time cannot precede the expected snapshot time",
            )
        if event.occurred_at != updated.updated_at or event.final_state != updated.final_state:
            raise StateInvariantError(
                StateInvariantCause.EVENT_MISMATCH,
                "event time and final state must match the resulting snapshot",
            )

    @property
    def next_checkpoint(self) -> RunCheckpoint:
        """Return the immutable checkpoint produced after a successful CAS."""
        return RunCheckpoint(
            identity=self.expected.identity,
            lifecycle=self.advance.lifecycle,
        )


def create_initial_checkpoint(identity: RunIdentity) -> RunCheckpoint:
    """Create revision zero bound to an immutable run identity."""
    trusted_identity = _require_instance(identity, name="identity", expected=RunIdentity)
    return RunCheckpoint(
        identity=trusted_identity,
        lifecycle=start_lifecycle(trusted_identity),
    )


def prepare_state_update(
    checkpoint: RunCheckpoint,
    *,
    to_state: LifecycleState,
    occurred_at: datetime,
    actor: LifecycleActor,
    final_state: FinalState | None = None,
) -> StateUpdate:
    """Prepare one validated update without reading or writing a store."""
    current = _require_instance(checkpoint, name="checkpoint", expected=RunCheckpoint)
    advance = advance_lifecycle(
        current.lifecycle,
        to_state=to_state,
        occurred_at=occurred_at,
        actor=actor,
        final_state=final_state,
    )
    return StateUpdate(expected=current, advance=advance)
