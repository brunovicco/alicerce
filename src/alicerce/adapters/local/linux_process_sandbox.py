"""Linux process isolation backed by a pinned bubblewrap executable."""

import hashlib
import os
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self, cast

from alicerce.adapters.local.process_sandbox import (
    SandboxError,
    SandboxErrorCause,
    SandboxInvocation,
    SandboxResult,
)
from alicerce.domain.command import ExecutionTermination, NetworkPolicy

_READ_CHUNK_BYTES = 64 * 1024
_PROBE_TIMEOUT_SECONDS = 5.0
_SANDBOX_EXECUTABLE = Path("/alicerce/executable")
_SANDBOX_WORKSPACE = Path("/workspace")


def _file_sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.digest()


@dataclass(frozen=True, slots=True)
class _PinnedBubblewrap:
    path: Path
    sha256: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        path = self.path
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("bubblewrap path must be absolute and not a symlink")
        try:
            resolved = path.resolve(strict=True)
            if resolved != path or not resolved.is_file() or not os.access(resolved, os.X_OK):
                raise ValueError("bubblewrap path must identify an executable regular file")
            digest = _file_sha256(resolved)
        except OSError as error:
            raise ValueError("bubblewrap path is unavailable") from error
        object.__setattr__(self, "path", resolved)
        object.__setattr__(self, "sha256", digest)

    def verify(self) -> None:
        try:
            if (
                self.path.is_symlink()
                or self.path.resolve(strict=True) != self.path
                or not self.path.is_file()
                or not os.access(self.path, os.X_OK)
                or _file_sha256(self.path) != self.sha256
            ):
                raise SandboxError(
                    SandboxErrorCause.ISOLATION_FAILURE,
                    "bubblewrap executable changed",
                )
        except OSError as error:
            raise SandboxError(
                SandboxErrorCause.ISOLATION_FAILURE,
                "bubblewrap executable is unavailable",
            ) from error


class _Capture:
    """Close registered process streams deterministically."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self.selector = selectors.DefaultSelector()

    def __enter__(self) -> Self:
        for name, stream in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
            if stream is None:
                raise SandboxError(SandboxErrorCause.SPAWN_FAILED, f"missing {name} pipe")
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, name)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.selector.close()
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


class LinuxProcessSandboxBackend:
    """Run one command inside a fail-closed Linux bubblewrap sandbox."""

    _bubblewrap: _PinnedBubblewrap

    def __init__(self, bubblewrap_path: object) -> None:
        """Pin the explicitly configured bubblewrap executable."""
        if sys.platform != "linux":
            raise OSError("LinuxProcessSandboxBackend requires Linux")
        if not isinstance(bubblewrap_path, Path):
            raise TypeError("bubblewrap_path must be Path")
        self._bubblewrap = _PinnedBubblewrap(bubblewrap_path)

    def supports(self, network_policy: NetworkPolicy) -> bool:
        """Probe whether Linux can create the required deny-all sandbox."""
        if network_policy is not NetworkPolicy.DENY_ALL:
            return False
        self._bubblewrap.verify()
        command = self._base_command()
        command.extend(("--", "/usr/bin/true"))
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={},
                timeout=_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    def execute(self, invocation: object) -> SandboxResult:
        """Enforce isolation, timeout, bounded capture, and tree cleanup."""
        if not isinstance(invocation, SandboxInvocation):
            raise TypeError("invocation must be SandboxInvocation")
        if invocation.network_policy is not NetworkPolicy.DENY_ALL or not self.supports(
            invocation.network_policy
        ):
            raise SandboxError(
                SandboxErrorCause.ISOLATION_FAILURE,
                "required Linux isolation is unavailable",
            )
        self._bubblewrap.verify()
        command = self._build_command(invocation)
        started_at = datetime.now(UTC)
        try:
            process = subprocess.Popen(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd="/",
                env={},
                start_new_session=True,
                close_fds=True,
            )
        except OSError as error:
            raise SandboxError(SandboxErrorCause.SPAWN_FAILED, "bubblewrap spawn failed") from error

        termination = ExecutionTermination.EXITED
        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + invocation.limits.timeout_ms / 1000
        try:
            with _Capture(process) as capture:
                while capture.selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        termination = ExecutionTermination.TIMED_OUT
                        break
                    events = capture.selector.select(remaining)
                    if not events and process.poll() is None:
                        continue
                    for key, _mask in events:
                        stream = cast(BinaryIO, key.fileobj)
                        try:
                            chunk = os.read(stream.fileno(), _READ_CHUNK_BYTES)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            capture.selector.unregister(stream)
                            continue
                        target = stdout if key.data == "stdout" else stderr
                        ceiling = (
                            invocation.limits.stdout_max_bytes
                            if key.data == "stdout"
                            else invocation.limits.stderr_max_bytes
                        )
                        available = max(0, ceiling - len(target))
                        target.extend(chunk[:available])
                        if len(chunk) > available:
                            termination = ExecutionTermination.OUTPUT_LIMIT
                            break
                    if termination is not ExecutionTermination.EXITED:
                        break
            if termination is not ExecutionTermination.EXITED:
                self._terminate_tree(process, invocation.limits.termination_grace_ms)
                exit_code = None
            else:
                exit_code = process.wait()
        except OSError as error:
            self._terminate_tree(process, invocation.limits.termination_grace_ms)
            raise SandboxError(SandboxErrorCause.CLEANUP_FAILED, "capture failed") from error
        finally:
            self._bubblewrap.verify()
        return SandboxResult(
            termination=termination,
            exit_code=exit_code,
            stdout=bytes(stdout),
            stderr=bytes(stderr),
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    def _base_command(self) -> list[str]:
        return [
            str(self._bubblewrap.path),
            "--unshare-net",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--ro-bind",
            "/usr",
            "/usr",
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
        ]

    def _build_command(self, invocation: SandboxInvocation) -> list[str]:
        workspace = invocation.workspace_root
        try:
            relative_working_directory = invocation.working_directory.relative_to(workspace)
        except ValueError as error:
            raise SandboxError(
                SandboxErrorCause.ISOLATION_FAILURE,
                "working directory is outside the workspace",
            ) from error

        sandbox_working_directory = _SANDBOX_WORKSPACE / relative_working_directory
        command = self._base_command()
        command.extend(("--dir", "/alicerce"))
        command.extend(("--ro-bind", str(invocation.executable), str(_SANDBOX_EXECUTABLE)))
        command.extend(("--chmod", "0555", "/alicerce"))
        command.extend(("--dir", str(_SANDBOX_WORKSPACE)))
        command.extend(("--bind", str(workspace), str(_SANDBOX_WORKSPACE)))
        command.extend(("--chdir", str(sandbox_working_directory)))
        for entry in invocation.environment:
            command.extend(("--setenv", entry.name, entry.value))
        command.append("--")
        command.append(str(_SANDBOX_EXECUTABLE))
        command.extend(invocation.arguments)
        return command

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[bytes], grace_ms: int) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=grace_ms / 1000)
                return
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=max(grace_ms / 1000, 0.1))
        except (OSError, subprocess.SubprocessError) as error:
            raise SandboxError(
                SandboxErrorCause.CLEANUP_FAILED,
                "process tree cleanup failed",
            ) from error
