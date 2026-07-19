"""Tests for the pure monotonic run lifecycle policy."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from alicerce.application import advance_lifecycle, start_lifecycle
from alicerce.domain.contracts import FINAL_STATES
from alicerce.domain.lifecycle import (
    LifecycleActor,
    LifecycleAdvance,
    LifecycleError,
    LifecycleErrorCause,
    LifecycleState,
    LifecycleTransition,
    RunLifecycle,
)
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)

NOW = datetime(2026, 7, 19, 18, 0, tzinfo=UTC)
ACTOR = LifecycleActor("core.lifecycle")
NORMAL_PATH = (
    LifecycleState.CONTRACT_BOUND,
    LifecycleState.WORKSPACE_PREPARED,
    LifecycleState.BUILDING,
    LifecycleState.VERIFYING,
    LifecycleState.DECIDING,
    LifecycleState.REVIEW_PENDING,
    LifecycleState.COMPLETED,
)


def _identity() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-001"),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        created_at=NOW,
    )


def _snapshot(
    state: LifecycleState,
    *,
    revision: int = 0,
    updated_at: datetime = NOW,
    final_state: str | None = None,
) -> RunLifecycle:
    return RunLifecycle(
        run_id=RunId("run-001"),
        state=state,
        revision=revision,
        updated_at=updated_at,
        final_state=final_state,  # type: ignore[arg-type]
    )


def test_lifecycle_starts_only_after_contract_binding() -> None:
    """Revision zero is bound to the already-created immutable identity."""
    lifecycle = start_lifecycle(_identity())
    assert lifecycle == _snapshot(LifecycleState.CONTRACT_BOUND)
    assert lifecycle.run_id == _identity().run_id
    assert lifecycle.updated_at == _identity().created_at


def test_normal_path_is_monotonic_and_attributed() -> None:
    """Every accepted step increments once and produces a matching event."""
    lifecycle = start_lifecycle(_identity())
    for expected_revision, target in enumerate(NORMAL_PATH[1:], start=1):
        final_state = "SUCCEEDED" if target is LifecycleState.COMPLETED else None
        result = advance_lifecycle(
            lifecycle,
            to_state=target,
            occurred_at=NOW + timedelta(seconds=expected_revision),
            actor=ACTOR,
            final_state=final_state,
        )
        assert result.lifecycle.revision == expected_revision
        assert result.transition.revision == expected_revision
        assert result.transition.run_id == lifecycle.run_id
        assert result.transition.from_state is lifecycle.state
        assert result.transition.to_state is target
        assert result.transition.actor is ACTOR
        assert result.lifecycle.state is target
        lifecycle = result.lifecycle


@pytest.mark.parametrize("state", NORMAL_PATH[:-1])
def test_every_nonterminal_state_can_fail_closed_to_completion(state: LifecycleState) -> None:
    """Early termination remains explicit and carries a canonical outcome."""
    result = advance_lifecycle(
        _snapshot(state),
        to_state=LifecycleState.COMPLETED,
        occurred_at=NOW,
        actor=ACTOR,
        final_state="INFRA_FAILED",
    )
    assert result.lifecycle.final_state == "INFRA_FAILED"
    assert result.transition.final_state == "INFRA_FAILED"


@pytest.mark.parametrize("final_state", FINAL_STATES)
def test_completion_accepts_every_canonical_final_state(final_state: str) -> None:
    """Internal completion reuses the complete canonical final-state vocabulary."""
    result = advance_lifecycle(
        _snapshot(LifecycleState.DECIDING),
        to_state=LifecycleState.COMPLETED,
        occurred_at=NOW,
        actor=ACTOR,
        final_state=final_state,  # type: ignore[arg-type]
    )
    assert result.lifecycle.final_state == final_state


def test_internal_states_are_disjoint_from_canonical_final_states() -> None:
    """Working state names cannot masquerade as serialized final states."""
    assert {state.value for state in LifecycleState}.isdisjoint(FINAL_STATES)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (LifecycleState.CONTRACT_BOUND, LifecycleState.BUILDING),
        (LifecycleState.WORKSPACE_PREPARED, LifecycleState.VERIFYING),
        (LifecycleState.BUILDING, LifecycleState.DECIDING),
        (LifecycleState.VERIFYING, LifecycleState.REVIEW_PENDING),
        (LifecycleState.DECIDING, LifecycleState.WORKSPACE_PREPARED),
        (LifecycleState.REVIEW_PENDING, LifecycleState.DECIDING),
        (LifecycleState.BUILDING, LifecycleState.BUILDING),
    ],
)
def test_skips_backtracking_and_self_transitions_are_rejected(
    source: LifecycleState,
    target: LifecycleState,
) -> None:
    """Only explicitly allowlisted monotonic transitions are accepted."""
    with pytest.raises(LifecycleError) as captured:
        advance_lifecycle(
            _snapshot(source),
            to_state=target,
            occurred_at=NOW,
            actor=ACTOR,
        )
    assert captured.value.cause is LifecycleErrorCause.INVALID_TRANSITION


def test_completed_lifecycle_is_terminal() -> None:
    """No event can be appended after internal completion."""
    with pytest.raises(LifecycleError) as captured:
        advance_lifecycle(
            _snapshot(LifecycleState.COMPLETED, final_state="SUCCEEDED"),
            to_state=LifecycleState.COMPLETED,
            occurred_at=NOW,
            actor=ACTOR,
            final_state="SUCCEEDED",
        )
    assert captured.value.cause is LifecycleErrorCause.TERMINAL_STATE


def test_time_cannot_regress_but_equal_instants_are_allowed() -> None:
    """Monotonic time permits deterministic equal-clock transitions."""
    lifecycle = _snapshot(LifecycleState.CONTRACT_BOUND)
    with pytest.raises(LifecycleError) as captured:
        advance_lifecycle(
            lifecycle,
            to_state=LifecycleState.WORKSPACE_PREPARED,
            occurred_at=NOW - timedelta(microseconds=1),
            actor=ACTOR,
        )
    assert captured.value.cause is LifecycleErrorCause.TIME_REGRESSION

    accepted = advance_lifecycle(
        lifecycle,
        to_state=LifecycleState.WORKSPACE_PREPARED,
        occurred_at=NOW,
        actor=ACTOR,
    )
    assert accepted.lifecycle.updated_at == NOW


def test_completion_requires_final_state_and_working_states_forbid_it() -> None:
    """Canonical outcomes exist if and only if the lifecycle is completed."""
    with pytest.raises(LifecycleError) as required:
        advance_lifecycle(
            _snapshot(LifecycleState.DECIDING),
            to_state=LifecycleState.COMPLETED,
            occurred_at=NOW,
            actor=ACTOR,
        )
    assert required.value.cause is LifecycleErrorCause.FINAL_STATE_REQUIRED

    with pytest.raises(LifecycleError) as forbidden:
        advance_lifecycle(
            _snapshot(LifecycleState.DECIDING),
            to_state=LifecycleState.REVIEW_PENDING,
            occurred_at=NOW,
            actor=ACTOR,
            final_state="SUCCEEDED",
        )
    assert forbidden.value.cause is LifecycleErrorCause.FINAL_STATE_FORBIDDEN


def test_invalid_final_state_is_rejected() -> None:
    """A local outcome cannot extend the canonical vocabulary."""
    with pytest.raises(TypeError, match="canonical FinalState"):
        advance_lifecycle(
            _snapshot(LifecycleState.DECIDING),
            to_state=LifecycleState.COMPLETED,
            occurred_at=NOW,
            actor=ACTOR,
            final_state="FAILED",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", ["", "Core", ".core", "core actor", "core/actor", "a" * 65])
def test_actor_rejects_invalid_component_names(value: str) -> None:
    """Attribution uses bounded provider-neutral component identities."""
    with pytest.raises(ValueError):
        LifecycleActor(value)


def test_actor_rejects_non_string_and_projects_explicitly() -> None:
    """Actor values reject coercion and expose deliberate string projection."""
    with pytest.raises(TypeError):
        LifecycleActor(1)  # type: ignore[arg-type]
    assert str(ACTOR) == "core.lifecycle"


def test_snapshots_events_results_and_actors_are_frozen_and_slotted() -> None:
    """Lifecycle facts cannot be modified after construction."""
    result = advance_lifecycle(
        _snapshot(LifecycleState.CONTRACT_BOUND),
        to_state=LifecycleState.WORKSPACE_PREPARED,
        occurred_at=NOW,
        actor=ACTOR,
    )
    for value in (ACTOR, result.lifecycle, result.transition, result):
        assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.lifecycle.revision = 99  # type: ignore[misc]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _snapshot(LifecycleState.COMPLETED),
        lambda: LifecycleTransition(
            run_id=RunId("run-001"),
            revision=1,
            from_state=LifecycleState.DECIDING,
            to_state=LifecycleState.COMPLETED,
            occurred_at=NOW,
            actor=ACTOR,
        ),
    ],
)
def test_direct_terminal_facts_require_final_state(factory: Callable[[], object]) -> None:
    """Direct construction cannot bypass terminal outcome requirements."""
    with pytest.raises(LifecycleError) as captured:
        factory()
    assert captured.value.cause is LifecycleErrorCause.FINAL_STATE_REQUIRED


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _snapshot(LifecycleState.DECIDING, final_state="SUCCEEDED"),
        lambda: LifecycleTransition(
            run_id=RunId("run-001"),
            revision=1,
            from_state=LifecycleState.VERIFYING,
            to_state=LifecycleState.DECIDING,
            occurred_at=NOW,
            actor=ACTOR,
            final_state="SUCCEEDED",
        ),
    ],
)
def test_direct_working_facts_forbid_final_state(factory: Callable[[], object]) -> None:
    """Direct construction cannot attach outcomes before completion."""
    with pytest.raises(LifecycleError) as captured:
        factory()
    assert captured.value.cause is LifecycleErrorCause.FINAL_STATE_FORBIDDEN


@pytest.mark.parametrize("revision", [-1, True, 1.5, "1"])
def test_revision_must_be_a_nonnegative_integer(revision: object) -> None:
    """Revision cannot be negative or exploit bool-as-int behavior."""
    expected = ValueError if revision == -1 else TypeError
    with pytest.raises(expected):
        RunLifecycle(
            run_id=RunId("run-001"),
            state=LifecycleState.CONTRACT_BOUND,
            revision=revision,  # type: ignore[arg-type]
            updated_at=NOW,
        )


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 7, 19, 18, 0),
        datetime(2026, 7, 19, 18, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_snapshot_requires_explicit_utc_singleton(instant: datetime) -> None:
    """Snapshots reject naive and noncanonical timezone objects."""
    with pytest.raises(ValueError, match="UTC"):
        _snapshot(LifecycleState.CONTRACT_BOUND, updated_at=instant)


def test_runtime_type_confusion_is_rejected() -> None:
    """Defensive checks protect callers outside static type checking."""
    with pytest.raises(TypeError, match="identity"):
        start_lifecycle(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="state"):
        RunLifecycle(
            run_id=RunId("run-001"),
            state="contract_bound",  # type: ignore[arg-type]
            revision=0,
            updated_at=NOW,
        )
    with pytest.raises(TypeError, match="LifecycleTransition"):
        LifecycleAdvance(
            lifecycle=_snapshot(LifecycleState.CONTRACT_BOUND),
            transition=object(),  # type: ignore[arg-type]
        )
