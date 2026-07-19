"""Pure monotonic lifecycle policy for trusted runs."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from alicerce.domain.contracts import FINAL_STATES, FinalState
from alicerce.domain.run_identity import RunId, RunIdentity

_ACTOR_PATTERN: Final = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")


class LifecycleState(StrEnum):
    """Internal working states that are never canonical final states."""

    CONTRACT_BOUND = "contract_bound"
    WORKSPACE_PREPARED = "workspace_prepared"
    BUILDING = "building"
    VERIFYING = "verifying"
    DECIDING = "deciding"
    REVIEW_PENDING = "review_pending"
    COMPLETED = "completed"


class LifecycleErrorCause(StrEnum):
    """Typed causes for rejected lifecycle operations."""

    INVALID_TRANSITION = "invalid_transition"
    TERMINAL_STATE = "terminal_state"
    TIME_REGRESSION = "time_regression"
    FINAL_STATE_REQUIRED = "final_state_required"
    FINAL_STATE_FORBIDDEN = "final_state_forbidden"


class LifecycleError(ValueError):
    """Raised when a lifecycle operation violates trusted policy."""

    def __init__(self, cause: LifecycleErrorCause, detail: str) -> None:
        """Record a stable typed cause."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


@dataclass(frozen=True, slots=True)
class LifecycleActor:
    """Trusted component identity attributed to a transition."""

    value: str

    def __post_init__(self) -> None:
        """Reject ambiguous or unsafe component names."""
        value = _require_instance(self.value, name="actor", expected=str)
        if _ACTOR_PATTERN.fullmatch(value) is None:
            raise ValueError("actor has an invalid format")

    def __str__(self) -> str:
        """Return the wrapped component identity."""
        return self.value


_ALLOWED_NEXT: Final[dict[LifecycleState, frozenset[LifecycleState]]] = {
    LifecycleState.CONTRACT_BOUND: frozenset(
        {LifecycleState.WORKSPACE_PREPARED, LifecycleState.COMPLETED}
    ),
    LifecycleState.WORKSPACE_PREPARED: frozenset(
        {LifecycleState.BUILDING, LifecycleState.COMPLETED}
    ),
    LifecycleState.BUILDING: frozenset({LifecycleState.VERIFYING, LifecycleState.COMPLETED}),
    LifecycleState.VERIFYING: frozenset({LifecycleState.DECIDING, LifecycleState.COMPLETED}),
    LifecycleState.DECIDING: frozenset({LifecycleState.REVIEW_PENDING, LifecycleState.COMPLETED}),
    LifecycleState.REVIEW_PENDING: frozenset({LifecycleState.COMPLETED}),
    LifecycleState.COMPLETED: frozenset(),
}


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _require_utc(value: object, *, name: str) -> datetime:
    instant = _require_instance(value, name=name, expected=datetime)
    if instant.tzinfo is not UTC:
        raise ValueError(f"{name} must use UTC timezone")
    return instant


def _require_revision(value: object) -> int:
    if type(value) is not int:
        raise TypeError("revision must be an integer")
    if value < 0:
        raise ValueError("revision must be non-negative")
    return value


def _require_final_state(value: object) -> FinalState:
    if value not in FINAL_STATES:
        raise TypeError("final_state must be a canonical FinalState")
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class RunLifecycle:
    """Immutable current lifecycle snapshot for one run."""

    run_id: RunId
    state: LifecycleState
    revision: int
    updated_at: datetime
    final_state: FinalState | None = None

    def __post_init__(self) -> None:
        """Enforce snapshot type, time, and terminal invariants."""
        _require_instance(self.run_id, name="run_id", expected=RunId)
        state = _require_instance(self.state, name="state", expected=LifecycleState)
        _require_revision(self.revision)
        _require_utc(self.updated_at, name="updated_at")
        if state is LifecycleState.COMPLETED:
            if self.final_state is None:
                raise LifecycleError(
                    LifecycleErrorCause.FINAL_STATE_REQUIRED,
                    "completed lifecycle requires a canonical final state",
                )
            _require_final_state(self.final_state)
        elif self.final_state is not None:
            raise LifecycleError(
                LifecycleErrorCause.FINAL_STATE_FORBIDDEN,
                "non-terminal lifecycle cannot carry a final state",
            )


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    """Immutable attributed event for one accepted state change."""

    run_id: RunId
    revision: int
    from_state: LifecycleState
    to_state: LifecycleState
    occurred_at: datetime
    actor: LifecycleActor
    final_state: FinalState | None = None

    def __post_init__(self) -> None:
        """Enforce event types and terminal-state consistency."""
        _require_instance(self.run_id, name="run_id", expected=RunId)
        _require_revision(self.revision)
        _require_instance(self.from_state, name="from_state", expected=LifecycleState)
        to_state = _require_instance(self.to_state, name="to_state", expected=LifecycleState)
        _require_utc(self.occurred_at, name="occurred_at")
        _require_instance(self.actor, name="actor", expected=LifecycleActor)
        if to_state is LifecycleState.COMPLETED:
            if self.final_state is None:
                raise LifecycleError(
                    LifecycleErrorCause.FINAL_STATE_REQUIRED,
                    "completion event requires a canonical final state",
                )
            _require_final_state(self.final_state)
        elif self.final_state is not None:
            raise LifecycleError(
                LifecycleErrorCause.FINAL_STATE_FORBIDDEN,
                "non-terminal event cannot carry a final state",
            )


@dataclass(frozen=True, slots=True)
class LifecycleAdvance:
    """New snapshot and the event that produced it."""

    lifecycle: RunLifecycle
    transition: LifecycleTransition

    def __post_init__(self) -> None:
        """Ensure the result contains the expected domain types."""
        _require_instance(self.lifecycle, name="lifecycle", expected=RunLifecycle)
        _require_instance(
            self.transition,
            name="transition",
            expected=LifecycleTransition,
        )


def start_lifecycle(identity: RunIdentity) -> RunLifecycle:
    """Create the initial revision from an immutable run identity."""
    trusted_identity = _require_instance(identity, name="identity", expected=RunIdentity)
    return RunLifecycle(
        run_id=trusted_identity.run_id,
        state=LifecycleState.CONTRACT_BOUND,
        revision=0,
        updated_at=trusted_identity.created_at,
    )


def advance_lifecycle(
    lifecycle: RunLifecycle,
    *,
    to_state: LifecycleState,
    occurred_at: datetime,
    actor: LifecycleActor,
    final_state: FinalState | None = None,
) -> LifecycleAdvance:
    """Apply one allowed monotonic transition without mutating input state."""
    current = _require_instance(lifecycle, name="lifecycle", expected=RunLifecycle)
    target = _require_instance(to_state, name="to_state", expected=LifecycleState)
    instant = _require_utc(occurred_at, name="occurred_at")
    trusted_actor = _require_instance(actor, name="actor", expected=LifecycleActor)

    if current.state is LifecycleState.COMPLETED:
        raise LifecycleError(
            LifecycleErrorCause.TERMINAL_STATE,
            "completed lifecycle cannot transition",
        )
    if target not in _ALLOWED_NEXT[current.state]:
        raise LifecycleError(
            LifecycleErrorCause.INVALID_TRANSITION,
            f"{current.state.value} cannot transition to {target.value}",
        )
    if instant < current.updated_at:
        raise LifecycleError(
            LifecycleErrorCause.TIME_REGRESSION,
            "transition time cannot precede current snapshot time",
        )
    if target is LifecycleState.COMPLETED and final_state is None:
        raise LifecycleError(
            LifecycleErrorCause.FINAL_STATE_REQUIRED,
            "completion requires a canonical final state",
        )
    if target is not LifecycleState.COMPLETED and final_state is not None:
        raise LifecycleError(
            LifecycleErrorCause.FINAL_STATE_FORBIDDEN,
            "only completion may carry a canonical final state",
        )
    if final_state is not None:
        _require_final_state(final_state)

    revision = current.revision + 1
    transition = LifecycleTransition(
        run_id=current.run_id,
        revision=revision,
        from_state=current.state,
        to_state=target,
        occurred_at=instant,
        actor=trusted_actor,
        final_state=final_state,
    )
    updated = RunLifecycle(
        run_id=current.run_id,
        state=target,
        revision=revision,
        updated_at=instant,
        final_state=final_state,
    )
    return LifecycleAdvance(lifecycle=updated, transition=transition)
