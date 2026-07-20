"""Executable contract tests for the provider-neutral workspace port."""

from datetime import UTC, datetime

import pytest

from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)
from alicerce.domain.workspace import (
    CandidateIdentity,
    CandidateSha,
    WorkspaceId,
    WorkspaceIdentity,
    bind_candidate,
)
from alicerce.ports.workspace import (
    WorkspaceError,
    WorkspaceErrorCause,
    WorkspacePort,
)

NOW = datetime(2026, 7, 20, 1, 0, tzinfo=UTC)


class MemoryWorkspacePort:
    """Test-only reference implementation using capability handles only."""

    def __init__(self) -> None:
        self._workspaces: dict[WorkspaceId, WorkspaceIdentity] = {}
        self._run_index: dict[RunId, WorkspaceId] = {}
        self._next_id = 1

    def prepare(self, identity: RunIdentity) -> WorkspaceIdentity:
        if identity.run_id in self._run_index:
            raise WorkspaceError(WorkspaceErrorCause.ALREADY_EXISTS, str(identity.run_id))
        workspace = WorkspaceIdentity(
            workspace_id=WorkspaceId(f"workspace-{self._next_id}"),
            run_id=identity.run_id,
            baseline_sha=identity.baseline_sha,
        )
        self._next_id += 1
        self._workspaces[workspace.workspace_id] = workspace
        self._run_index[workspace.run_id] = workspace.workspace_id
        return workspace

    def load(self, workspace_id: WorkspaceId) -> WorkspaceIdentity | None:
        return self._workspaces.get(workspace_id)

    def snapshot(self, workspace: WorkspaceIdentity) -> CandidateIdentity:
        current = self._workspaces.get(workspace.workspace_id)
        if current is None:
            raise WorkspaceError(WorkspaceErrorCause.NOT_FOUND, str(workspace.workspace_id))
        if current != workspace:
            raise WorkspaceError(WorkspaceErrorCause.CONFLICT, str(workspace.workspace_id))
        return bind_candidate(current, CandidateSha("d" * 40))

    def release(self, workspace: WorkspaceIdentity) -> None:
        current = self._workspaces.get(workspace.workspace_id)
        if current is None:
            return
        if current != workspace:
            raise WorkspaceError(WorkspaceErrorCause.CONFLICT, str(workspace.workspace_id))
        del self._workspaces[workspace.workspace_id]
        del self._run_index[workspace.run_id]


def _identity(run_id: str = "run-workspace") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(run_id),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        created_at=NOW,
    )


def test_reference_double_structurally_satisfies_workspace_port() -> None:
    port: WorkspacePort = MemoryWorkspacePort()
    workspace = port.prepare(_identity())
    assert port.load(workspace.workspace_id) == workspace


def test_prepare_is_exclusive_and_binds_run_baseline() -> None:
    port = MemoryWorkspacePort()
    identity = _identity()
    workspace = port.prepare(identity)
    assert workspace.run_id == identity.run_id
    assert workspace.baseline_sha == identity.baseline_sha
    with pytest.raises(WorkspaceError) as duplicate:
        port.prepare(identity)
    assert duplicate.value.cause is WorkspaceErrorCause.ALREADY_EXISTS


def test_snapshot_binds_candidate_to_current_workspace() -> None:
    port = MemoryWorkspacePort()
    workspace = port.prepare(_identity())
    candidate = port.snapshot(workspace)
    assert candidate.workspace == workspace
    assert candidate.candidate_sha == CandidateSha("d" * 40)


def test_missing_and_stale_workspace_handles_fail_explicitly() -> None:
    port = MemoryWorkspacePort()
    workspace = port.prepare(_identity())
    missing = WorkspaceIdentity(
        WorkspaceId("missing"),
        workspace.run_id,
        workspace.baseline_sha,
    )
    with pytest.raises(WorkspaceError) as not_found:
        port.snapshot(missing)
    assert not_found.value.cause is WorkspaceErrorCause.NOT_FOUND

    stale = WorkspaceIdentity(
        workspace.workspace_id,
        RunId("another-run"),
        workspace.baseline_sha,
    )
    with pytest.raises(WorkspaceError) as conflict:
        port.snapshot(stale)
    assert conflict.value.cause is WorkspaceErrorCause.CONFLICT
    with pytest.raises(WorkspaceError) as release_conflict:
        port.release(stale)
    assert release_conflict.value.cause is WorkspaceErrorCause.CONFLICT


def test_release_is_idempotent_and_removes_capability() -> None:
    port = MemoryWorkspacePort()
    workspace = port.prepare(_identity())
    port.release(workspace)
    port.release(workspace)
    assert port.load(workspace.workspace_id) is None
    with pytest.raises(WorkspaceError) as missing:
        port.snapshot(workspace)
    assert missing.value.cause is WorkspaceErrorCause.NOT_FOUND


def test_released_run_can_prepare_a_new_capability() -> None:
    port = MemoryWorkspacePort()
    first = port.prepare(_identity())
    port.release(first)
    second = port.prepare(_identity())
    assert second.workspace_id != first.workspace_id


def test_workspace_error_exposes_stable_cause_and_message() -> None:
    error = WorkspaceError(WorkspaceErrorCause.ISOLATION_FAILURE, "overlap")
    assert error.cause is WorkspaceErrorCause.ISOLATION_FAILURE
    assert str(error) == "isolation_failure: overlap"
    assert WorkspaceErrorCause.STORAGE_FAILURE.value == "storage_failure"
