"""Tests for immutable checkpoints and validated state updates."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from alicerce.application.state import create_initial_checkpoint, prepare_state_update
from alicerce.domain.lifecycle import (
    LifecycleActor,
    LifecycleAdvance,
    LifecycleState,
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
from alicerce.domain.state import (
    RunCheckpoint,
    StateInvariantCause,
    StateInvariantError,
    StateUpdate,
)

NOW = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
ACTOR = LifecycleActor("core.state")


def _identity(run_id: str = "run-state") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(run_id),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        created_at=NOW,
    )


def _advance(checkpoint: RunCheckpoint) -> LifecycleAdvance:
    return prepare_state_update(
        checkpoint,
        to_state=LifecycleState.WORKSPACE_PREPARED,
        occurred_at=NOW + timedelta(seconds=1),
        actor=ACTOR,
    ).advance


def test_initial_checkpoint_is_revision_zero_bound_to_identity() -> None:
    identity = _identity()
    checkpoint = create_initial_checkpoint(identity)
    assert checkpoint.identity is identity
    assert checkpoint.lifecycle.run_id == identity.run_id
    assert checkpoint.lifecycle.state is LifecycleState.CONTRACT_BOUND
    assert checkpoint.lifecycle.revision == 0
    assert checkpoint.lifecycle.updated_at == identity.created_at


def test_checkpoint_rejects_mismatched_run_and_regressing_time() -> None:
    identity = _identity()
    with pytest.raises(StateInvariantError) as mismatched:
        RunCheckpoint(
            identity=identity,
            lifecycle=RunLifecycle(
                run_id=RunId("another-run"),
                state=LifecycleState.CONTRACT_BOUND,
                revision=0,
                updated_at=NOW,
            ),
        )
    assert mismatched.value.cause is StateInvariantCause.RUN_MISMATCH

    with pytest.raises(StateInvariantError) as regressed:
        RunCheckpoint(
            identity=identity,
            lifecycle=RunLifecycle(
                run_id=identity.run_id,
                state=LifecycleState.CONTRACT_BOUND,
                revision=0,
                updated_at=NOW - timedelta(microseconds=1),
            ),
        )
    assert regressed.value.cause is StateInvariantCause.TIME_REGRESSION


def test_update_composes_expected_checkpoint_event_and_result() -> None:
    checkpoint = create_initial_checkpoint(_identity())
    update = prepare_state_update(
        checkpoint,
        to_state=LifecycleState.WORKSPACE_PREPARED,
        occurred_at=NOW + timedelta(seconds=1),
        actor=ACTOR,
    )
    assert update.expected is checkpoint
    assert update.advance.transition.from_state is checkpoint.lifecycle.state
    assert update.next_checkpoint == RunCheckpoint(
        identity=checkpoint.identity,
        lifecycle=update.advance.lifecycle,
    )


def test_update_rejects_run_revision_state_time_and_event_mismatches() -> None:
    checkpoint = create_initial_checkpoint(_identity())
    advance = _advance(checkpoint)

    bad_run = LifecycleAdvance(
        lifecycle=replace(advance.lifecycle, run_id=RunId("another-run")),
        transition=advance.transition,
    )
    with pytest.raises(StateInvariantError) as run_error:
        StateUpdate(checkpoint, bad_run)
    assert run_error.value.cause is StateInvariantCause.RUN_MISMATCH

    bad_revision = LifecycleAdvance(
        lifecycle=replace(advance.lifecycle, revision=2),
        transition=advance.transition,
    )
    with pytest.raises(StateInvariantError) as revision_error:
        StateUpdate(checkpoint, bad_revision)
    assert revision_error.value.cause is StateInvariantCause.REVISION_MISMATCH

    bad_state = LifecycleAdvance(
        lifecycle=advance.lifecycle,
        transition=replace(advance.transition, from_state=LifecycleState.BUILDING),
    )
    with pytest.raises(StateInvariantError) as state_error:
        StateUpdate(checkpoint, bad_state)
    assert state_error.value.cause is StateInvariantCause.STATE_MISMATCH

    earlier = NOW - timedelta(microseconds=1)
    bad_time = LifecycleAdvance(
        lifecycle=replace(advance.lifecycle, updated_at=earlier),
        transition=replace(advance.transition, occurred_at=earlier),
    )
    with pytest.raises(StateInvariantError) as time_error:
        StateUpdate(checkpoint, bad_time)
    assert time_error.value.cause is StateInvariantCause.TIME_REGRESSION

    bad_event = LifecycleAdvance(
        lifecycle=advance.lifecycle,
        transition=replace(
            advance.transition,
            occurred_at=advance.transition.occurred_at + timedelta(microseconds=1),
        ),
    )
    with pytest.raises(StateInvariantError) as event_error:
        StateUpdate(checkpoint, bad_event)
    assert event_error.value.cause is StateInvariantCause.EVENT_MISMATCH


def test_checkpoint_and_update_reject_untrusted_component_types() -> None:
    checkpoint = create_initial_checkpoint(_identity())
    with pytest.raises(TypeError, match="identity must be RunIdentity"):
        RunCheckpoint(object(), checkpoint.lifecycle)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="lifecycle must be RunLifecycle"):
        RunCheckpoint(checkpoint.identity, object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="expected must be RunCheckpoint"):
        StateUpdate(object(), _advance(checkpoint))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="advance must be LifecycleAdvance"):
        StateUpdate(checkpoint, object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="identity must be RunIdentity"):
        create_initial_checkpoint(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="checkpoint must be RunCheckpoint"):
        prepare_state_update(
            object(),  # type: ignore[arg-type]
            to_state=LifecycleState.WORKSPACE_PREPARED,
            occurred_at=NOW,
            actor=ACTOR,
        )


def test_checkpoint_and_update_are_frozen_and_slotted() -> None:
    checkpoint = create_initial_checkpoint(_identity())
    update = StateUpdate(checkpoint, _advance(checkpoint))
    for value in (checkpoint, update):
        assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        checkpoint.identity = _identity("replacement")  # type: ignore[misc]


def test_invariant_error_exposes_stable_cause_and_message() -> None:
    error = StateInvariantError(StateInvariantCause.EVENT_MISMATCH, "broken event")
    assert error.cause is StateInvariantCause.EVENT_MISMATCH
    assert str(error) == "event_mismatch: broken event"
