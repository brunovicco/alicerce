"""Local coordination between authorized commands and a sandbox backend."""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import cast

from alicerce.adapters.local.git_workspace import LocalGitWorkspace
from alicerce.adapters.local.process_sandbox import (
    ProcessSandboxBackend,
    SandboxError,
    SandboxErrorCause,
    SandboxInvocation,
)
from alicerce.domain.command import ExecutableId, ExecutionResult, WorkingDirectory
from alicerce.domain.command_policy import (
    AuthorizedCommand,
    CommandAuthorizationError,
    authorize_command,
)
from alicerce.ports.command_executor import (
    CommandExecutionError,
    CommandExecutionErrorCause,
)
from alicerce.ports.workspace import WorkspaceError, WorkspaceErrorCause

_READ_CHUNK_BYTES = 1024 * 1024


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _require_tuple(value: object, *, name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple")
    return cast(tuple[object, ...], value)


def _file_sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.digest()


@dataclass(frozen=True, slots=True)
class TrustedExecutable:
    """Pinned logical executable mapped to one exact local file."""

    executable_id: ExecutableId
    path: Path
    sha256: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Resolve and hash an absolute executable without PATH lookup."""
        _require_instance(
            self.executable_id,
            name="executable_id",
            expected=ExecutableId,
        )
        path = _require_instance(self.path, name="path", expected=Path)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("executable path must be absolute and not a symlink")
        try:
            resolved = path.resolve(strict=True)
            if resolved != path or not resolved.is_file() or not os.access(resolved, os.X_OK):
                raise ValueError("executable path must identify an executable regular file")
            digest = _file_sha256(resolved)
        except OSError as error:
            raise ValueError("executable path is unavailable") from error
        object.__setattr__(self, "path", resolved)
        object.__setattr__(self, "sha256", digest)

    def verify(self) -> None:
        """Fail closed if path identity, executable status, or content changed."""
        try:
            if (
                self.path.is_symlink()
                or self.path.resolve(strict=True) != self.path
                or not self.path.is_file()
                or not os.access(self.path, os.X_OK)
                or _file_sha256(self.path) != self.sha256
            ):
                raise CommandExecutionError(
                    CommandExecutionErrorCause.ISOLATION_FAILURE,
                    "trusted executable changed",
                )
        except OSError as error:
            raise CommandExecutionError(
                CommandExecutionErrorCause.EXECUTABLE_UNAVAILABLE,
                "trusted executable is unavailable",
            ) from error


class LocalCommandExecutor:
    """Coordinate trusted local execution without implementing a process backend."""

    def __init__(
        self,
        *,
        workspace: LocalGitWorkspace,
        executables: tuple[TrustedExecutable, ...],
        sandbox: ProcessSandboxBackend,
    ) -> None:
        """Bind workspace capabilities, executable registry, and trusted sandbox."""
        self._workspace = _require_instance(
            workspace,
            name="workspace",
            expected=LocalGitWorkspace,
        )
        raw_executables = _require_tuple(executables, name="executables")
        trusted = tuple(
            _require_instance(
                executable,
                name="executable",
                expected=TrustedExecutable,
            )
            for executable in raw_executables
        )
        identifiers = tuple(executable.executable_id.value for executable in trusted)
        if identifiers != tuple(sorted(identifiers)) or len(identifiers) != len(set(identifiers)):
            raise ValueError("executables must be unique and sorted by identifier")
        backend = cast(object, sandbox)
        if not callable(getattr(backend, "supports", None)) or not callable(
            getattr(backend, "execute", None)
        ):
            raise TypeError("sandbox must provide supports and execute")
        self._executables = {executable.executable_id: executable for executable in trusted}
        self._sandbox = sandbox

    def execute(self, command: AuthorizedCommand) -> ExecutionResult:
        """Reauthorize, resolve trusted capabilities, and invoke the sandbox seam."""
        command = _require_instance(command, name="command", expected=AuthorizedCommand)
        try:
            reauthorized = authorize_command(command.request, command.policy)
        except CommandAuthorizationError as error:
            raise CommandExecutionError(
                CommandExecutionErrorCause.POLICY_DENIED,
                "command authorization failed",
            ) from error
        if reauthorized != command:
            raise CommandExecutionError(
                CommandExecutionErrorCause.POLICY_DENIED,
                "command authorization changed",
            )
        executable = self._executables.get(command.request.executable)
        if executable is None:
            raise CommandExecutionError(
                CommandExecutionErrorCause.EXECUTABLE_UNAVAILABLE,
                command.request.executable.value,
            )
        if not self._sandbox.supports(command.request.network_policy):
            raise CommandExecutionError(
                CommandExecutionErrorCause.POLICY_DENIED,
                "sandbox cannot enforce requested network policy",
            )
        executable.verify()
        try:
            with self._workspace.execution_lease(command.request.workspace) as root:
                working_directory = self._resolve_working_directory(
                    root,
                    command.request.working_directory,
                )
                executable.verify()
                invocation = SandboxInvocation(
                    executable=executable.path,
                    arguments=command.request.arguments,
                    workspace_root=root,
                    working_directory=working_directory,
                    environment=command.request.environment,
                    network_policy=command.request.network_policy,
                    limits=command.request.limits,
                )
                try:
                    sandbox_result = self._sandbox.execute(invocation)
                except SandboxError as error:
                    raise self._translate_sandbox_error(error) from error
                executable.verify()
                try:
                    return ExecutionResult(
                        request=command.request,
                        termination=sandbox_result.termination,
                        exit_code=sandbox_result.exit_code,
                        stdout=sandbox_result.stdout,
                        stderr=sandbox_result.stderr,
                        started_at=sandbox_result.started_at,
                        finished_at=sandbox_result.finished_at,
                    )
                except (TypeError, ValueError, AttributeError) as error:
                    raise CommandExecutionError(
                        CommandExecutionErrorCause.ISOLATION_FAILURE,
                        "sandbox returned an invalid result",
                    ) from error
        except WorkspaceError as error:
            cause = (
                CommandExecutionErrorCause.WORKSPACE_NOT_FOUND
                if error.cause is WorkspaceErrorCause.NOT_FOUND
                else CommandExecutionErrorCause.ISOLATION_FAILURE
            )
            raise CommandExecutionError(cause, "workspace execution lease failed") from error

    @staticmethod
    def _resolve_working_directory(root: Path, relative: WorkingDirectory) -> Path:
        parts = () if relative.value == "." else PurePosixPath(relative.value).parts
        candidate = root
        for part in parts:
            candidate /= part
            if candidate.is_symlink():
                raise CommandExecutionError(
                    CommandExecutionErrorCause.ISOLATION_FAILURE,
                    "working directory traverses a symlink",
                )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise CommandExecutionError(
                CommandExecutionErrorCause.ISOLATION_FAILURE,
                "working directory is unavailable",
            ) from error
        if not resolved.is_dir() or not resolved.is_relative_to(root):
            raise CommandExecutionError(
                CommandExecutionErrorCause.ISOLATION_FAILURE,
                "working directory escapes its workspace",
            )
        return resolved

    @staticmethod
    def _translate_sandbox_error(error: SandboxError) -> CommandExecutionError:
        causes = {
            SandboxErrorCause.SPAWN_FAILED: CommandExecutionErrorCause.SPAWN_FAILED,
            SandboxErrorCause.CLEANUP_FAILED: CommandExecutionErrorCause.CLEANUP_FAILED,
            SandboxErrorCause.ISOLATION_FAILURE: CommandExecutionErrorCause.ISOLATION_FAILURE,
        }
        return CommandExecutionError(causes[error.cause], "process sandbox failed")
