"""Executable contract tests for provider-neutral state stores."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from alicerce.application.state import create_initial_checkpoint, prepare_state_update
from alicerce.domain.lifecycle import LifecycleActor, LifecycleState, LifecycleTransition
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)
from alicerce.domain.state import RunCheckpoint, StateUpdate
from alicerce.ports.state_store import (
    StateStoreError,
    StateStoreErrorCause,
    StateStorePort,
)

NOW = datetime(2026, 7, 19, 21, 0, tzinfo=UTC)
ACTOR = LifecycleActor("test.store")


class MemoryStateStore:
    """Test-only reference implementation of the port contract."""

    def __init__(self) -> None:
        self._current: dict[RunId, RunCheckpoint] = {}
        self._history: dict[RunId, list[LifecycleTransition]] = {}

    def initialize(self, checkpoint: RunCheckpoint) -> None:
        run_id = checkpoint.identity.run_id
        if run_id in self._current:
            raise StateStoreError(StateStoreErrorCause.ALREADY_EXISTS, str(run_id))
        if checkpoint != create_initial_checkpoint(checkpoint.identity):
            raise StateStoreError(
                StateStoreErrorCause.CONFLICT,
                "checkpoint must be the identity-derived initial state",
            )
        self._current[run_id] = checkpoint
        self._history[run_id] = []

    def load(self, run_id: RunId) -> RunCheckpoint | None:
        return self._current.get(run_id)

    def compare_and_append(self, update: StateUpdate) -> RunCheckpoint:
        run_id = update.expected.identity.run_id
        current = self._current.get(run_id)
        if current is None:
            raise StateStoreError(StateStoreErrorCause.NOT_FOUND, str(run_id))
        if current != update.expected:
            raise StateStoreError(StateStoreErrorCause.CONFLICT, str(run_id))
        next_checkpoint = update.next_checkpoint
        self._history[run_id].append(update.advance.transition)
        self._current[run_id] = next_checkpoint
        return next_checkpoint

    def history(self, run_id: RunId) -> tuple[LifecycleTransition, ...]:
        events = self._history.get(run_id)
        if events is None:
            raise StateStoreError(StateStoreErrorCause.NOT_FOUND, str(run_id))
        return tuple(events)


def _identity(run_id: str = "run-store", *, policy: str = "c") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(run_id),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash(policy * 64),
        created_at=NOW,
    )


def _update(checkpoint: RunCheckpoint, seconds: int = 1) -> StateUpdate:
    return prepare_state_update(
        checkpoint,
        to_state=LifecycleState.WORKSPACE_PREPARED,
        occurred_at=NOW + timedelta(seconds=seconds),
        actor=ACTOR,
    )


def test_reference_double_structurally_satisfies_port() -> None:
    store: StateStorePort = MemoryStateStore()
    assert store.load(RunId("absent")) is None


def test_initialize_is_exclusive_and_requires_revision_zero() -> None:
    store = MemoryStateStore()
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    assert store.load(initial.identity.run_id) is initial

    with pytest.raises(StateStoreError) as duplicate:
        store.initialize(initial)
    assert duplicate.value.cause is StateStoreErrorCause.ALREADY_EXISTS

    noninitial = _update(create_initial_checkpoint(_identity("noninitial"))).next_checkpoint
    with pytest.raises(StateStoreError) as revision:
        store.initialize(noninitial)
    assert revision.value.cause is StateStoreErrorCause.CONFLICT

    wrong_state = RunCheckpoint(
        identity=_identity("wrong-state"),
        lifecycle=replace(
            create_initial_checkpoint(_identity("wrong-state")).lifecycle,
            state=LifecycleState.WORKSPACE_PREPARED,
        ),
    )
    with pytest.raises(StateStoreError) as state:
        store.initialize(wrong_state)
    assert state.value.cause is StateStoreErrorCause.CONFLICT


def test_compare_and_append_atomically_advances_and_records_history() -> None:
    store = MemoryStateStore()
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    update = _update(initial)

    current = store.compare_and_append(update)
    assert current == update.next_checkpoint
    assert store.load(initial.identity.run_id) == current
    assert store.history(initial.identity.run_id) == (update.advance.transition,)


def test_stale_or_identity_changed_precondition_fails_without_append() -> None:
    store = MemoryStateStore()
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    accepted = store.compare_and_append(_update(initial))

    with pytest.raises(StateStoreError) as stale:
        store.compare_and_append(_update(initial, seconds=2))
    assert stale.value.cause is StateStoreErrorCause.CONFLICT

    changed_identity = RunCheckpoint(identity=_identity(policy="d"), lifecycle=accepted.lifecycle)
    changed_update = prepare_state_update(
        changed_identity,
        to_state=LifecycleState.BUILDING,
        occurred_at=NOW + timedelta(seconds=2),
        actor=ACTOR,
    )
    with pytest.raises(StateStoreError) as changed:
        store.compare_and_append(changed_update)
    assert changed.value.cause is StateStoreErrorCause.CONFLICT
    assert store.load(initial.identity.run_id) == accepted
    assert len(store.history(initial.identity.run_id)) == 1


def test_missing_update_and_history_have_typed_not_found_failure() -> None:
    store = MemoryStateStore()
    initial = create_initial_checkpoint(_identity())
    with pytest.raises(StateStoreError) as update_error:
        store.compare_and_append(_update(initial))
    assert update_error.value.cause is StateStoreErrorCause.NOT_FOUND

    with pytest.raises(StateStoreError) as history_error:
        store.history(initial.identity.run_id)
    assert history_error.value.cause is StateStoreErrorCause.NOT_FOUND


def test_history_is_an_immutable_revision_ordered_snapshot() -> None:
    store = MemoryStateStore()
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    first = _update(initial)
    current = store.compare_and_append(first)
    second = prepare_state_update(
        current,
        to_state=LifecycleState.BUILDING,
        occurred_at=NOW + timedelta(seconds=2),
        actor=ACTOR,
    )
    store.compare_and_append(second)
    history = store.history(initial.identity.run_id)
    assert isinstance(history, tuple)
    assert [event.revision for event in history] == [1, 2]


def test_store_error_exposes_stable_cause_and_message() -> None:
    error = StateStoreError(StateStoreErrorCause.CONFLICT, "run-store")
    assert error.cause is StateStoreErrorCause.CONFLICT
    assert str(error) == "conflict: run-store"
