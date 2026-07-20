"""Provider-neutral capability boundary for isolated candidate workspaces."""

from enum import StrEnum
from typing import Protocol

from alicerce.domain.run_identity import RunIdentity
from alicerce.domain.workspace import CandidateIdentity, WorkspaceId, WorkspaceIdentity


class WorkspaceErrorCause(StrEnum):
    """Stable operational causes exposed by workspace implementations."""

    ALREADY_EXISTS = "already_exists"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    ISOLATION_FAILURE = "isolation_failure"
    STORAGE_FAILURE = "storage_failure"


class WorkspaceError(RuntimeError):
    """Raised when a workspace operation cannot honor its contract."""

    def __init__(self, cause: WorkspaceErrorCause, detail: str) -> None:
        """Record a stable typed cause."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


class WorkspacePort(Protocol):
    """Prepare, recover, snapshot, and idempotently release capability handles."""

    def prepare(self, identity: RunIdentity) -> WorkspaceIdentity:
        """Prepare one isolated workspace bound to the run baseline."""
        ...

    def load(self, workspace_id: WorkspaceId) -> WorkspaceIdentity | None:
        """Return a prepared workspace identity, or ``None`` when absent."""
        ...

    def snapshot(self, workspace: WorkspaceIdentity) -> CandidateIdentity:
        """Return the trusted immutable identity of current candidate content."""
        ...

    def release(self, workspace: WorkspaceIdentity) -> None:
        """Idempotently dispose of the workspace owned by the supplied handle."""
        ...
