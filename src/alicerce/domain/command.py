"""Immutable provider-neutral values for controlled command execution."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, cast

from alicerce.domain.run_identity import RunIdentity
from alicerce.domain.workspace import WorkspaceIdentity

_EXECUTABLE_ID_PATTERN: Final = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
_ACTION_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ENVIRONMENT_NAME_PATTERN: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _require_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _require_pattern(
    value: object,
    *,
    name: str,
    pattern: re.Pattern[str],
) -> str:
    text = _require_string(value, name=name)
    if pattern.fullmatch(text) is None:
        raise ValueError(f"{name} has an invalid format")
    return text


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _require_positive_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class ExecutableId:
    """Logical identifier mapped to a trusted executable by an adapter."""

    value: str

    def __post_init__(self) -> None:
        """Reject paths and ambiguous executable identifiers."""
        _require_pattern(
            self.value,
            name="executable_id",
            pattern=_EXECUTABLE_ID_PATTERN,
        )

    def __str__(self) -> str:
        """Return the wrapped logical identifier."""
        return self.value


@dataclass(frozen=True, slots=True)
class CommandAction:
    """Semantic action name checked against trusted run policy before spawn."""

    value: str

    def __post_init__(self) -> None:
        """Reject empty, unbounded, or structurally unsafe action names."""
        _require_pattern(self.value, name="command_action", pattern=_ACTION_PATTERN)

    def __str__(self) -> str:
        """Return the wrapped action name."""
        return self.value


@dataclass(frozen=True, slots=True)
class WorkingDirectory:
    """Normalized POSIX-relative directory inside an opaque workspace."""

    value: str

    def __post_init__(self) -> None:
        """Reject absolute, escaping, platform-dependent, or ambiguous paths."""
        value = _require_string(self.value, name="working_directory")
        if value == ".":
            return
        path = PurePosixPath(value)
        if (
            not value
            or "\0" in value
            or "\\" in value
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {".", ".."} for part in path.parts)
        ):
            raise ValueError("working_directory must be a normalized relative POSIX path")

    def __str__(self) -> str:
        """Return the normalized relative directory."""
        return self.value


@dataclass(frozen=True, slots=True)
class EnvironmentVariable:
    """One explicitly permitted environment entry."""

    name: str
    value: str

    def __post_init__(self) -> None:
        """Reject invalid names and values that cannot enter an environment."""
        _require_pattern(
            self.name,
            name="environment variable name",
            pattern=_ENVIRONMENT_NAME_PATTERN,
        )
        value = _require_string(self.value, name="environment variable value")
        if "\0" in value:
            raise ValueError("environment variable value cannot contain NUL")


class NetworkPolicy(StrEnum):
    """Network authority requested for one execution."""

    DENY_ALL = "deny_all"


@dataclass(frozen=True, slots=True)
class CommandLimits:
    """Hard execution and captured-output ceilings."""

    timeout_ms: int
    termination_grace_ms: int
    stdout_max_bytes: int
    stderr_max_bytes: int

    def __post_init__(self) -> None:
        """Require explicit positive integer ceilings without bool coercion."""
        _require_positive_integer(self.timeout_ms, name="timeout_ms")
        _require_positive_integer(self.termination_grace_ms, name="termination_grace_ms")
        _require_positive_integer(self.stdout_max_bytes, name="stdout_max_bytes")
        _require_positive_integer(self.stderr_max_bytes, name="stderr_max_bytes")


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """Trusted execution request addressed through a workspace capability."""

    run_identity: RunIdentity
    workspace: WorkspaceIdentity
    action: CommandAction
    executable: ExecutableId
    arguments: tuple[str, ...]
    working_directory: WorkingDirectory
    environment: tuple[EnvironmentVariable, ...]
    network_policy: NetworkPolicy
    limits: CommandLimits

    def __post_init__(self) -> None:
        """Reject semantic confusion and nondeterministic request components."""
        run_identity = _require_instance(
            self.run_identity,
            name="run_identity",
            expected=RunIdentity,
        )
        workspace = _require_instance(
            self.workspace,
            name="workspace",
            expected=WorkspaceIdentity,
        )
        if (
            workspace.run_id != run_identity.run_id
            or workspace.baseline_sha != run_identity.baseline_sha
        ):
            raise ValueError("workspace does not match the complete run identity")
        _require_instance(self.action, name="action", expected=CommandAction)
        _require_instance(self.executable, name="executable", expected=ExecutableId)
        raw_arguments = cast(object, self.arguments)
        if not isinstance(raw_arguments, tuple):
            raise TypeError("arguments must be a tuple")
        arguments = cast(tuple[object, ...], raw_arguments)
        for argument in arguments:
            text = _require_string(argument, name="argument")
            if "\0" in text:
                raise ValueError("argument cannot contain NUL")
        _require_instance(
            self.working_directory,
            name="working_directory",
            expected=WorkingDirectory,
        )
        raw_environment = cast(object, self.environment)
        if not isinstance(raw_environment, tuple):
            raise TypeError("environment must be a tuple")
        entries = tuple(
            _require_instance(entry, name="environment entry", expected=EnvironmentVariable)
            for entry in cast(tuple[object, ...], raw_environment)
        )
        names = tuple(entry.name for entry in entries)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("environment must have unique entries sorted by name")
        _require_instance(
            self.network_policy,
            name="network_policy",
            expected=NetworkPolicy,
        )
        _require_instance(self.limits, name="limits", expected=CommandLimits)


class ExecutionTermination(StrEnum):
    """Stable reason that command execution stopped."""

    EXITED = "exited"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    OUTPUT_LIMIT = "output_limit"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Bounded operational result that is never authoritative evidence itself."""

    request: CommandRequest
    termination: ExecutionTermination
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    started_at: datetime
    finished_at: datetime

    def __post_init__(self) -> None:
        """Require a coherent result bound to its request and UTC interval."""
        request = _require_instance(self.request, name="request", expected=CommandRequest)
        termination = _require_instance(
            self.termination,
            name="termination",
            expected=ExecutionTermination,
        )
        if termination is ExecutionTermination.EXITED:
            if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
                raise TypeError("exit_code must be an integer for an exited command")
        elif self.exit_code is not None:
            raise ValueError("exit_code must be None when a command did not exit normally")
        stdout = _require_instance(self.stdout, name="stdout", expected=bytes)
        stderr = _require_instance(self.stderr, name="stderr", expected=bytes)
        if len(stdout) > request.limits.stdout_max_bytes:
            raise ValueError("stdout exceeds its configured ceiling")
        if len(stderr) > request.limits.stderr_max_bytes:
            raise ValueError("stderr exceeds its configured ceiling")
        started_at = _require_instance(self.started_at, name="started_at", expected=datetime)
        finished_at = _require_instance(self.finished_at, name="finished_at", expected=datetime)
        if started_at.tzinfo is not UTC or finished_at.tzinfo is not UTC:
            raise ValueError("execution timestamps must use UTC timezone")
        if finished_at < started_at:
            raise ValueError("finished_at cannot precede started_at")
