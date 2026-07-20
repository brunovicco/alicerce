"""Tests for immutable workspace and candidate capability identities."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from alicerce.domain.run_identity import BaselineSha, RunId
from alicerce.domain.workspace import (
    CandidateIdentity,
    CandidateSha,
    WorkspaceId,
    WorkspaceIdentity,
    bind_candidate,
)


def _workspace() -> WorkspaceIdentity:
    return WorkspaceIdentity(
        workspace_id=WorkspaceId("workspace-001"),
        run_id=RunId("run-001"),
        baseline_sha=BaselineSha("b" * 40),
    )


@pytest.mark.parametrize(
    "value",
    ["workspace", "Workspace_01", "1", "a.b-c_d", "a" * 128],
)
def test_workspace_id_accepts_bounded_path_safe_handles(value: str) -> None:
    assert str(WorkspaceId(value)) == value


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "-workspace", "workspace/name", "workspace name", "a" * 129],
)
def test_workspace_id_rejects_unsafe_or_unbounded_handles(value: str) -> None:
    with pytest.raises(ValueError):
        WorkspaceId(value)


def test_workspace_id_rejects_non_string_without_coercion() -> None:
    with pytest.raises(TypeError, match="workspace_id must be a string"):
        WorkspaceId(1)  # type: ignore[arg-type]


@pytest.mark.parametrize("length", [40, 64])
def test_candidate_sha_accepts_complete_lowercase_object_ids(length: int) -> None:
    value = "a" * length
    assert str(CandidateSha(value)) == value


@pytest.mark.parametrize(
    "value",
    ["", "a" * 7, "a" * 39, "a" * 41, "a" * 63, "a" * 65, "A" * 40, "g" * 40],
)
def test_candidate_sha_rejects_abbreviated_or_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        CandidateSha(value)


def test_candidate_sha_rejects_non_string_without_coercion() -> None:
    with pytest.raises(TypeError, match="candidate_sha must be a string"):
        CandidateSha(1)  # type: ignore[arg-type]


def test_workspace_binds_run_and_baseline_without_exposing_a_path() -> None:
    workspace = _workspace()
    assert workspace.workspace_id == WorkspaceId("workspace-001")
    assert workspace.run_id == RunId("run-001")
    assert workspace.baseline_sha == BaselineSha("b" * 40)
    assert set(workspace.__dataclass_fields__) == {
        "workspace_id",
        "run_id",
        "baseline_sha",
    }


def test_candidate_identity_preserves_complete_workspace_binding() -> None:
    workspace = _workspace()
    candidate = bind_candidate(workspace, CandidateSha("c" * 40))
    assert candidate == CandidateIdentity(
        workspace=workspace,
        candidate_sha=CandidateSha("c" * 40),
    )
    assert candidate.workspace is workspace


def test_candidate_and_baseline_hashes_remain_semantically_distinct() -> None:
    text = "d" * 40
    assert CandidateSha(text) != BaselineSha(text)
    candidate = bind_candidate(
        WorkspaceIdentity(WorkspaceId("workspace"), RunId("run"), BaselineSha(text)),
        CandidateSha(text),
    )
    assert candidate.workspace.baseline_sha.value == candidate.candidate_sha.value


@pytest.mark.parametrize(
    "factory",
    [
        lambda: WorkspaceIdentity(  # type: ignore[arg-type]
            object(),  # pyright: ignore[reportArgumentType]
            RunId("run"),
            BaselineSha("b" * 40),
        ),
        lambda: WorkspaceIdentity(  # type: ignore[arg-type]
            WorkspaceId("workspace"),
            object(),  # pyright: ignore[reportArgumentType]
            BaselineSha("b" * 40),
        ),
        lambda: WorkspaceIdentity(  # type: ignore[arg-type]
            WorkspaceId("workspace"),
            RunId("run"),
            object(),  # pyright: ignore[reportArgumentType]
        ),
        lambda: CandidateIdentity(  # type: ignore[arg-type]
            object(),  # pyright: ignore[reportArgumentType]
            CandidateSha("c" * 40),
        ),
        lambda: CandidateIdentity(_workspace(), object()),  # type: ignore[arg-type]
        lambda: bind_candidate(  # type: ignore[arg-type]
            object(),  # pyright: ignore[reportArgumentType]
            CandidateSha("c" * 40),
        ),
        lambda: bind_candidate(_workspace(), object()),  # type: ignore[arg-type]
    ],
)
def test_semantic_components_reject_type_confusion(factory: Callable[[], object]) -> None:
    with pytest.raises(TypeError):
        factory()


def test_workspace_and_candidate_values_are_frozen_and_slotted() -> None:
    workspace = _workspace()
    candidate = bind_candidate(workspace, CandidateSha("c" * 40))
    for value in (workspace.workspace_id, candidate.candidate_sha, workspace, candidate):
        assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        workspace.run_id = RunId("changed")  # type: ignore[misc]
