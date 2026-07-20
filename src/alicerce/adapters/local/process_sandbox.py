"""Adapter-private seam for a future OS-enforced process sandbox."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from alicerce.domain.command import (
    CommandLimits,
    EnvironmentVariable,
    ExecutionTermination,
    NetworkPolicy,
)


@dataclass(frozen=True, slots=True)
class SandboxInvocation:
    """Trusted host-level invocation prepared by the local coordinator."""

    executable: Path
    arguments: tuple[str, ...]
    workspace_root: Path
    working_directory: Path
    environment: tuple[EnvironmentVariable, ...]
    network_policy: NetworkPolicy
    limits: CommandLimits


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """Raw bounded result returned by a trusted sandbox backend."""

    termination: ExecutionTermination
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    started_at: datetime
    finished_at: datetime


class SandboxErrorCause(StrEnum):
    """Stable failures reported by an adapter-private sandbox backend."""

    SPAWN_FAILED = "spawn_failed"
    CLEANUP_FAILED = "cleanup_failed"
    ISOLATION_FAILURE = "isolation_failure"


class SandboxError(RuntimeError):
    """Report a backend failure without inspecting captured output."""

    def __init__(self, cause: SandboxErrorCause, detail: str) -> None:
        """Record the trusted backend cause."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


class ProcessSandboxBackend(Protocol):
    """Execute only invocations prepared by the local coordinator."""

    def supports(self, network_policy: NetworkPolicy) -> bool:
        """Return whether the backend enforces the requested network policy."""
        ...

    def execute(self, invocation: SandboxInvocation) -> SandboxResult:
        """Execute without a shell and return bounded captured output."""
        ...
