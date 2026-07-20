"""Immutable capability identities for isolated candidate workspaces."""

import re
from dataclasses import dataclass
from typing import Final

from alicerce.domain.run_identity import BaselineSha, RunId

_WORKSPACE_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CANDIDATE_SHA_PATTERN: Final = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _require_pattern(
    value: object,
    *,
    name: str,
    pattern: re.Pattern[str],
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid format")
    return value


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    """Opaque path-safe capability handle for one local workspace."""

    value: str

    def __post_init__(self) -> None:
        """Reject ambiguous, unsafe, or unbounded handles."""
        _require_pattern(
            self.value,
            name="workspace_id",
            pattern=_WORKSPACE_ID_PATTERN,
        )

    def __str__(self) -> str:
        """Return the wrapped capability handle."""
        return self.value


@dataclass(frozen=True, slots=True)
class CandidateSha:
    """Complete immutable object identity for one candidate snapshot."""

    value: str

    def __post_init__(self) -> None:
        """Reject abbreviated or noncanonical object identifiers."""
        _require_pattern(
            self.value,
            name="candidate_sha",
            pattern=_CANDIDATE_SHA_PATTERN,
        )

    def __str__(self) -> str:
        """Return the wrapped object identifier."""
        return self.value


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    """Immutable binding from a capability handle to one run baseline."""

    workspace_id: WorkspaceId
    run_id: RunId
    baseline_sha: BaselineSha

    def __post_init__(self) -> None:
        """Reject semantic type confusion at the isolation boundary."""
        _require_instance(
            self.workspace_id,
            name="workspace_id",
            expected=WorkspaceId,
        )
        _require_instance(self.run_id, name="run_id", expected=RunId)
        _require_instance(
            self.baseline_sha,
            name="baseline_sha",
            expected=BaselineSha,
        )


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """Immutable candidate snapshot bound to its originating workspace."""

    workspace: WorkspaceIdentity
    candidate_sha: CandidateSha

    def __post_init__(self) -> None:
        """Require the exact semantic workspace and candidate types."""
        _require_instance(
            self.workspace,
            name="workspace",
            expected=WorkspaceIdentity,
        )
        _require_instance(
            self.candidate_sha,
            name="candidate_sha",
            expected=CandidateSha,
        )


def bind_candidate(
    workspace: WorkspaceIdentity,
    candidate_sha: CandidateSha,
) -> CandidateIdentity:
    """Bind a trusted snapshot identity without filesystem or Git behavior."""
    return CandidateIdentity(
        workspace=_require_instance(
            workspace,
            name="workspace",
            expected=WorkspaceIdentity,
        ),
        candidate_sha=_require_instance(
            candidate_sha,
            name="candidate_sha",
            expected=CandidateSha,
        ),
    )
