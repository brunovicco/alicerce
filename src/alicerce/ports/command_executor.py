"""Provider-neutral port for controlled command execution."""

from enum import StrEnum
from typing import Protocol

from alicerce.domain.command import CommandRequest, ExecutionResult


class CommandExecutionErrorCause(StrEnum):
    """Stable operational failures exposed by command executors."""

    POLICY_DENIED = "policy_denied"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    EXECUTABLE_UNAVAILABLE = "executable_unavailable"
    SPAWN_FAILED = "spawn_failed"
    CLEANUP_FAILED = "cleanup_failed"
    ISOLATION_FAILURE = "isolation_failure"


class CommandExecutionError(RuntimeError):
    """Raised when controlled execution cannot produce a trusted result."""

    def __init__(self, cause: CommandExecutionErrorCause, detail: str) -> None:
        """Record a stable typed cause without interpreting output text."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


class CommandExecutorPort(Protocol):
    """Execute one validated request through a trusted adapter."""

    def execute(self, request: CommandRequest) -> ExecutionResult:
        """Return a bounded operational result or raise a typed failure."""
        ...
