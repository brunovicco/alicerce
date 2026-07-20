"""Tests for fail-closed persisted run identity validation."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alicerce.adapters.local.sqlite_state_store import SQLiteStateStore
from alicerce.application.contract_binding import bind_contract
from alicerce.application.resume import (
    ResumeError,
    ResumeErrorCause,
    load_run_for_resume,
)
from alicerce.domain.contract_binding import BoundContract
from alicerce.domain.lifecycle import LifecycleActor, LifecycleState, LifecycleTransition
from alicerce.domain.run_identity import (
    BaselineSha,
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
from alicerce.ports.state_store import StateStoreError, StateStoreErrorCause

NOW = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
BASELINE = BaselineSha("b" * 40)
POLICY = PolicyHash("c" * 64)


def _contract_bytes(contract_id: str = "quality-loop") -> bytes:
    return f'''{{
  "version": "0.1.2",
  "id": "{contract_id}",
  "objective": "Improve repository quality.",
  "trigger": {{"type": "manual"}},
  "selection": {{"strategy": "single-item"}},
  "baseline": {{"commands": ["quality"]}},
  "acceptance": {{"hard_gates": ["tests"]}},
  "budgets": {{"max_tokens": 1}},
  "scope": {{"allowlist": ["src/**"], "denylist": []}},
  "actions": {{"allowed": ["edit"], "denied": []}},
  "human_review": {{"required": true}}
}}'''.encode()


def _bound(contract_id: str = "quality-loop") -> BoundContract:
    return bind_contract(_contract_bytes(contract_id))


def _identity(
    *,
    run_id: str = "run-resume",
    bound_contract: BoundContract | None = None,
    contract_version: str | None = None,
) -> RunIdentity:
    binding = bound_contract or _bound()
    return RunIdentity(
        run_id=RunId(run_id),
        contract_id=ContractId(binding.contract.id),
        contract_version=ContractVersion(contract_version or binding.contract.version),
        contract_hash=binding.contract_hash,
        baseline_sha=BASELINE,
        policy_hash=POLICY,
        created_at=NOW,
    )


def _resume(store: SQLiteStateStore, binding: BoundContract | None = None) -> RunCheckpoint:
    return load_run_for_resume(
        run_id=RunId("run-resume"),
        bound_contract=binding or _bound(),
        baseline_sha=BASELINE,
        policy_hash=POLICY,
        state_store=store,
    )


def test_valid_nonterminal_checkpoint_resumes_after_store_reopen(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    reopened = SQLiteStateStore(database)
    assert _resume(reopened) == initial


@pytest.mark.parametrize("mismatch", ["id", "version", "hash"])
def test_changed_contract_binding_is_rejected(tmp_path: Path, mismatch: str) -> None:
    database = tmp_path / f"contract-{mismatch}.sqlite3"
    store = SQLiteStateStore(database)
    expected = _bound()
    if mismatch == "version":
        identity = _identity(contract_version="0.1.1")
        supplied = expected
    else:
        identity = _identity()
        supplied = (
            _bound("changed-contract")
            if mismatch == "id"
            else bind_contract(_contract_bytes() + b"\n")
        )
    initial = create_initial_checkpoint(identity)
    store.initialize(initial)

    with pytest.raises(ResumeError) as rejected:
        _resume(store, supplied)
    assert rejected.value.cause is ResumeErrorCause.CONTRACT_MISMATCH
    assert store.load(initial.identity.run_id) == initial
    assert store.history(initial.identity.run_id) == ()


@pytest.mark.parametrize(
    ("baseline", "policy", "cause"),
    [
        (BaselineSha("d" * 40), POLICY, ResumeErrorCause.BASELINE_MISMATCH),
        (BASELINE, PolicyHash("e" * 64), ResumeErrorCause.POLICY_MISMATCH),
    ],
)
def test_changed_baseline_or_policy_is_rejected_without_mutation(
    tmp_path: Path,
    baseline: BaselineSha,
    policy: PolicyHash,
    cause: ResumeErrorCause,
) -> None:
    database = tmp_path / f"{cause.value}.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    with pytest.raises(ResumeError) as rejected:
        load_run_for_resume(
            run_id=initial.identity.run_id,
            bound_contract=_bound(),
            baseline_sha=baseline,
            policy_hash=policy,
            state_store=store,
        )
    assert rejected.value.cause is cause
    assert store.load(initial.identity.run_id) == initial
    assert store.history(initial.identity.run_id) == ()


def test_missing_and_terminal_runs_cannot_resume(tmp_path: Path) -> None:
    missing_store = SQLiteStateStore(tmp_path / "missing.sqlite3")
    with pytest.raises(ResumeError) as missing:
        _resume(missing_store)
    assert missing.value.cause is ResumeErrorCause.NOT_FOUND

    terminal_store = SQLiteStateStore(tmp_path / "terminal.sqlite3")
    initial = create_initial_checkpoint(_identity())
    terminal_store.initialize(initial)
    terminal_store.compare_and_append(_terminal_update(initial))
    with pytest.raises(ResumeError) as terminal:
        _resume(terminal_store)
    assert terminal.value.cause is ResumeErrorCause.TERMINAL_RUN


def _terminal_update(checkpoint: RunCheckpoint) -> StateUpdate:
    return prepare_state_update(
        checkpoint,
        to_state=LifecycleState.COMPLETED,
        occurred_at=NOW,
        actor=LifecycleActor("test.resume"),
        final_state="INFRA_FAILED",
    )


class WrongRunStore:
    """Test-only port implementation that violates its lookup postcondition."""

    def __init__(self, checkpoint: RunCheckpoint) -> None:
        self.checkpoint = checkpoint

    def initialize(self, checkpoint: RunCheckpoint) -> None:
        raise AssertionError(checkpoint)

    def load(self, run_id: RunId) -> RunCheckpoint | None:
        return self.checkpoint

    def compare_and_append(self, update: StateUpdate) -> RunCheckpoint:
        raise AssertionError(update)

    def history(self, run_id: RunId) -> tuple[LifecycleTransition, ...]:
        raise AssertionError(run_id)


def test_store_returning_another_run_is_rejected() -> None:
    wrong = create_initial_checkpoint(_identity(run_id="another-run"))
    with pytest.raises(ResumeError) as mismatch:
        load_run_for_resume(
            run_id=RunId("run-resume"),
            bound_contract=_bound(),
            baseline_sha=BASELINE,
            policy_hash=POLICY,
            state_store=WrongRunStore(wrong),
        )
    assert mismatch.value.cause is ResumeErrorCause.RUN_MISMATCH


def test_corrupt_store_state_propagates_typed_store_failure(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.sqlite3"
    store = SQLiteStateStore(database)
    initial = create_initial_checkpoint(_identity())
    store.initialize(initial)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE alicerce_runs SET checkpoint = ? WHERE run_id = ?",
            (b"invalid", initial.identity.run_id.value),
        )
    with pytest.raises(StateStoreError) as corrupt:
        _resume(store)
    assert corrupt.value.cause is StateStoreErrorCause.CORRUPT


def test_resume_inputs_and_loaded_checkpoint_are_runtime_checked(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "state.sqlite3")
    cases = [
        {"run_id": object()},
        {"bound_contract": object()},
        {"baseline_sha": object()},
        {"policy_hash": object()},
    ]
    defaults: dict[str, object] = {
        "run_id": RunId("run-resume"),
        "bound_contract": _bound(),
        "baseline_sha": BASELINE,
        "policy_hash": POLICY,
        "state_store": store,
    }
    for override in cases:
        with pytest.raises(TypeError):
            load_run_for_resume(**{**defaults, **override})  # type: ignore[arg-type]

    class InvalidLoadStore(WrongRunStore):
        def load(self, run_id: RunId) -> RunCheckpoint | None:
            return object()  # type: ignore[return-value]

    with pytest.raises(TypeError, match="loaded checkpoint must be RunCheckpoint"):
        load_run_for_resume(
            run_id=RunId("run-resume"),
            bound_contract=_bound(),
            baseline_sha=BASELINE,
            policy_hash=POLICY,
            state_store=InvalidLoadStore(create_initial_checkpoint(_identity())),
        )


def test_resume_error_exposes_stable_cause_and_message() -> None:
    error = ResumeError(ResumeErrorCause.POLICY_MISMATCH, "changed")
    assert error.cause is ResumeErrorCause.POLICY_MISMATCH
    assert str(error) == "policy_mismatch: changed"
