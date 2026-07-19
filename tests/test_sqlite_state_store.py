"""Integration and corruption tests for the local SQLite state store."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alicerce.adapters.local.sqlite_state_store import SQLiteStateStore
from alicerce.adapters.local.state_serialization import (
    serialize_run_identity,
    serialize_transition,
)
from alicerce.domain.lifecycle import LifecycleActor, LifecycleState
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
    StateUpdate,
    create_initial_checkpoint,
    prepare_state_update,
)
from alicerce.ports.state_store import (
    StateStoreError,
    StateStoreErrorCause,
    StateStorePort,
)

NOW = datetime(2026, 7, 19, 23, 0, tzinfo=UTC)
ACTOR = LifecycleActor("test.sqlite")


def _identity(run_id: str = "run-sqlite", *, policy: str = "c") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(run_id),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash(policy * 64),
        created_at=NOW,
    )


def _update(
    checkpoint: RunCheckpoint,
    target: LifecycleState,
    seconds: int = 1,
) -> StateUpdate:
    return prepare_state_update(
        checkpoint,
        to_state=target,
        occurred_at=NOW + timedelta(seconds=seconds),
        actor=ACTOR,
    )


def _execute(database: Path, sql: str, parameters: tuple[object, ...] = ()) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(sql, parameters)


def test_adapter_structurally_satisfies_port_and_persists_across_instances(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    store: StateStorePort = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    update = _update(initial, LifecycleState.WORKSPACE_PREPARED)
    accepted = store.compare_and_append(update)

    reopened: StateStorePort = SQLiteStateStore(database)
    assert reopened.load(initial.identity.run_id) == accepted
    assert reopened.history(initial.identity.run_id) == (update.advance.transition,)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)


def test_initialization_is_exclusive_and_rejects_noninitial_checkpoint(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "state.sqlite3")
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    with pytest.raises(StateStoreError) as duplicate:
        store.initialize(initial)
    assert duplicate.value.cause is StateStoreErrorCause.ALREADY_EXISTS

    other = create_initial_checkpoint(_identity("other-run"))
    noninitial = _update(other, LifecycleState.WORKSPACE_PREPARED).next_checkpoint
    with pytest.raises(StateStoreError) as conflict:
        store.initialize(noninitial)
    assert conflict.value.cause is StateStoreErrorCause.CONFLICT


def test_missing_and_wrong_typed_operations_fail_explicitly(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "state.sqlite3")
    missing = create_initial_checkpoint(_identity())
    assert store.load(missing.identity.run_id) is None
    with pytest.raises(StateStoreError) as append_error:
        store.compare_and_append(_update(missing, LifecycleState.WORKSPACE_PREPARED))
    assert append_error.value.cause is StateStoreErrorCause.NOT_FOUND
    with pytest.raises(StateStoreError) as history_error:
        store.history(missing.identity.run_id)
    assert history_error.value.cause is StateStoreErrorCause.NOT_FOUND

    with pytest.raises(TypeError, match="checkpoint must be RunCheckpoint"):
        store.initialize(object())
    with pytest.raises(TypeError, match="run_id must be RunId"):
        store.load(object())
    with pytest.raises(TypeError, match="update must be StateUpdate"):
        store.compare_and_append(object())
    with pytest.raises(TypeError, match="run_id must be RunId"):
        store.history(object())


def test_two_concurrent_cas_attempts_have_exactly_one_winner(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    first_store = SQLiteStateStore(database)
    second_store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    first_store.initialize(initial)
    first_update = _update(initial, LifecycleState.WORKSPACE_PREPARED, 1)
    second_update = replace(
        first_update,
        advance=replace(
            first_update.advance,
            transition=replace(
                first_update.advance.transition,
                actor=LifecycleActor("test.concurrent"),
            ),
        ),
    )

    def attempt(store: SQLiteStateStore, update: object) -> str:
        try:
            store.compare_and_append(update)
        except StateStoreError as error:
            return error.cause.value
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                attempt,
                (first_store, second_store),
                (first_update, second_update),
            )
        )
    assert sorted(results) == ["accepted", "conflict"]
    assert len(first_store.history(initial.identity.run_id)) == 1


def test_identity_changed_precondition_conflicts_without_append(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "state.sqlite3")
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    changed = RunCheckpoint(
        identity=_identity(policy="d"),
        lifecycle=initial.lifecycle,
    )
    with pytest.raises(StateStoreError) as conflict:
        store.compare_and_append(_update(changed, LifecycleState.WORKSPACE_PREPARED))
    assert conflict.value.cause is StateStoreErrorCause.CONFLICT
    assert store.load(initial.identity.run_id) == initial
    assert store.history(initial.identity.run_id) == ()


def test_append_and_checkpoint_update_roll_back_together(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    _execute(
        database,
        """
        CREATE TRIGGER reject_checkpoint_update
        BEFORE UPDATE ON alicerce_runs
        BEGIN
            SELECT RAISE(ABORT, 'injected failure');
        END
        """,
    )

    with pytest.raises(StateStoreError) as failure:
        store.compare_and_append(_update(initial, LifecycleState.WORKSPACE_PREPARED))
    assert failure.value.cause is StateStoreErrorCause.STORAGE_FAILURE
    assert store.load(initial.identity.run_id) == initial
    assert store.history(initial.identity.run_id) == ()


def test_ordered_history_reconstructs_multiple_transitions(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "state.sqlite3")
    current = create_initial_checkpoint(_identity())
    store.initialize(current)
    expected_revisions: list[int] = []
    for revision, target in enumerate(
        (LifecycleState.WORKSPACE_PREPARED, LifecycleState.BUILDING, LifecycleState.VERIFYING),
        start=1,
    ):
        update = _update(current, target, revision)
        current = store.compare_and_append(update)
        expected_revisions.append(revision)
    assert store.load(current.identity.run_id) == current
    assert [event.revision for event in store.history(current.identity.run_id)] == (
        expected_revisions
    )


@pytest.mark.parametrize("column", ["identity", "checkpoint"])
def test_invalid_identity_or_checkpoint_bytes_fail_closed(tmp_path: Path, column: str) -> None:
    database = tmp_path / f"{column}.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    statement = (
        "UPDATE alicerce_runs SET identity = ? WHERE run_id = ?"
        if column == "identity"
        else "UPDATE alicerce_runs SET checkpoint = ? WHERE run_id = ?"
    )
    _execute(
        database,
        statement,
        (b"invalid", initial.identity.run_id.value),
    )
    with pytest.raises(StateStoreError) as corrupt:
        store.load(initial.identity.run_id)
    assert corrupt.value.cause is StateStoreErrorCause.CORRUPT


def test_identity_checkpoint_mismatch_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "mismatch.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    other = create_initial_checkpoint(_identity("other-run"))
    _execute(
        database,
        "UPDATE alicerce_runs SET identity = ? WHERE run_id = ?",
        (serialize_run_identity(other.identity), initial.identity.run_id.value),
    )
    with pytest.raises(StateStoreError) as corrupt:
        store.load(initial.identity.run_id)
    assert corrupt.value.cause is StateStoreErrorCause.CORRUPT


def test_transition_gap_invalid_event_and_checkpoint_divergence_fail_closed(
    tmp_path: Path,
) -> None:
    for corruption in ("gap", "event", "checkpoint"):
        database = tmp_path / f"{corruption}.sqlite3"
        store = SQLiteStateStore(database)
        current = create_initial_checkpoint(_identity(f"run-{corruption}"))
        store.initialize(current)
        first = _update(current, LifecycleState.WORKSPACE_PREPARED, 1)
        current = store.compare_and_append(first)
        second = _update(current, LifecycleState.BUILDING, 2)
        current = store.compare_and_append(second)
        if corruption == "gap":
            _execute(
                database,
                "DELETE FROM alicerce_transitions WHERE run_id = ? AND revision = 1",
                (current.identity.run_id.value,),
            )
        elif corruption == "event":
            _execute(
                database,
                "UPDATE alicerce_transitions SET transition = ? WHERE run_id = ? AND revision = 1",
                (b"{}", current.identity.run_id.value),
            )
        else:
            _execute(
                database,
                "DELETE FROM alicerce_transitions WHERE run_id = ? AND revision = 2",
                (current.identity.run_id.value,),
            )
        with pytest.raises(StateStoreError) as corrupt:
            store.load(current.identity.run_id)
        assert corrupt.value.cause is StateStoreErrorCause.CORRUPT


def test_valid_but_disconnected_transition_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "disconnected.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    update = _update(initial, LifecycleState.WORKSPACE_PREPARED)
    store.compare_and_append(update)
    disconnected = replace(
        update.advance.transition,
        from_state=LifecycleState.BUILDING,
    )
    _execute(
        database,
        "UPDATE alicerce_transitions SET transition = ? WHERE run_id = ?",
        (serialize_transition(disconnected), initial.identity.run_id.value),
    )
    with pytest.raises(StateStoreError) as corrupt:
        store.load(initial.identity.run_id)
    assert corrupt.value.cause is StateStoreErrorCause.CORRUPT


def test_cas_sql_precondition_is_checked_inside_transaction(tmp_path: Path) -> None:
    database = tmp_path / "sql-cas.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    _execute(
        database,
        """
        CREATE TRIGGER change_checkpoint_before_append
        BEFORE INSERT ON alicerce_transitions
        BEGIN
            UPDATE alicerce_runs SET checkpoint = x'00' WHERE run_id = NEW.run_id;
        END
        """,
    )
    with pytest.raises(StateStoreError) as conflict:
        store.compare_and_append(_update(initial, LifecycleState.WORKSPACE_PREPARED))
    assert conflict.value.cause is StateStoreErrorCause.CONFLICT
    assert store.load(initial.identity.run_id) == initial


def test_non_blob_values_are_classified_as_corrupt() -> None:
    with pytest.raises(StateStoreError) as corrupt:
        SQLiteStateStore._blob(  # pyright: ignore[reportPrivateUsage]
            "not-bytes",
            name="checkpoint",
        )
    assert corrupt.value.cause is StateStoreErrorCause.CORRUPT


def test_unknown_schema_and_sqlite_failures_are_typed(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(unknown) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(StateStoreError) as version:
        SQLiteStateStore(unknown)
    assert version.value.cause is StateStoreErrorCause.CORRUPT

    missing_parent = tmp_path / "missing" / "state.sqlite3"
    with pytest.raises(StateStoreError) as unavailable:
        SQLiteStateStore(missing_parent)
    assert unavailable.value.cause is StateStoreErrorCause.STORAGE_FAILURE

    broken = tmp_path / "broken.sqlite3"
    store = SQLiteStateStore(broken)
    _execute(broken, "DROP TABLE alicerce_runs")
    with pytest.raises(StateStoreError) as storage:
        store.load(RunId("run-sqlite"))
    assert storage.value.cause is StateStoreErrorCause.STORAGE_FAILURE

    initialize_broken = tmp_path / "initialize-broken.sqlite3"
    initialize_store = SQLiteStateStore(initialize_broken)
    _execute(initialize_broken, "DROP TABLE alicerce_runs")
    with pytest.raises(StateStoreError) as initialize_failure:
        initialize_store.initialize(create_initial_checkpoint(_identity()))
    assert initialize_failure.value.cause is StateStoreErrorCause.STORAGE_FAILURE

    history_broken = tmp_path / "history-broken.sqlite3"
    history_store = SQLiteStateStore(history_broken)
    initial = create_initial_checkpoint(_identity())
    history_store.initialize(initial)
    _execute(history_broken, "DROP TABLE alicerce_transitions")
    with pytest.raises(StateStoreError) as history_failure:
        history_store.history(initial.identity.run_id)
    assert history_failure.value.cause is StateStoreErrorCause.STORAGE_FAILURE


def test_partial_schema_creation_failure_rolls_back_and_is_typed(tmp_path: Path) -> None:
    database = tmp_path / "partial.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alicerce_transitions(value TEXT)")
    with pytest.raises(StateStoreError) as failure:
        SQLiteStateStore(database)
    assert failure.value.cause is StateStoreErrorCause.STORAGE_FAILURE


@pytest.mark.parametrize(
    ("database", "timeout", "error"),
    [
        (object(), 1.0, TypeError),
        ("", 1.0, ValueError),
        (":memory:", 1.0, ValueError),
        ("state.sqlite3", True, TypeError),
        ("state.sqlite3", -1, ValueError),
    ],
)
def test_constructor_rejects_invalid_configuration(
    tmp_path: Path,
    database: object,
    timeout: object,
    error: type[Exception],
) -> None:
    target = tmp_path / str(database) if database == "state.sqlite3" else database
    with pytest.raises(error):
        SQLiteStateStore(target, timeout_seconds=timeout)
