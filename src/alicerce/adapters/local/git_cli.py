"""Controlled Git CLI primitive for trusted local baseline materialization."""

import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Final, cast

from alicerce.domain.run_identity import BaselineSha

_DEFAULT_TIMEOUT_SECONDS: Final = 30.0
_DEFAULT_MAX_OUTPUT_BYTES: Final = 1_048_576


def _require_path(value: object, *, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be Path")
    return value


def _require_baseline(value: object) -> BaselineSha:
    if not isinstance(value, BaselineSha):
        raise TypeError("baseline_sha must be BaselineSha")
    return value


def _require_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timeout_seconds must be a number")
    if value <= 0:
        raise ValueError("timeout_seconds must be positive")
    return float(value)


def _require_output_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_output_bytes must be an integer")
    if value <= 0:
        raise ValueError("max_output_bytes must be positive")
    return value


class GitCliErrorCause(StrEnum):
    """Stable failure causes exposed by the controlled Git primitive."""

    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_PATH = "invalid_path"
    DESTINATION_EXISTS = "destination_exists"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    COMMAND_FAILED = "command_failed"
    BASELINE_MISMATCH = "baseline_mismatch"


class GitCliError(RuntimeError):
    """Raised when controlled baseline materialization fails closed."""

    def __init__(self, cause: GitCliErrorCause, detail: str) -> None:
        """Record a stable typed cause without exposing command output."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


@dataclass(frozen=True, slots=True)
class MaterializedBaseline:
    """Verified result of one independent detached baseline checkout."""

    repository: Path
    baseline_sha: BaselineSha

    def __post_init__(self) -> None:
        """Reject untrusted result construction."""
        repository = _require_path(self.repository, name="repository")
        if not repository.is_absolute():
            raise ValueError("repository must be absolute")
        _require_baseline(self.baseline_sha)


class ControlledGitCli:
    """Materialize exact local baselines through a constrained Git process."""

    def __init__(
        self,
        executable: Path,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        """Bind an absolute executable and fixed resource limits."""
        executable = _require_path(executable, name="executable")
        if not executable.is_absolute():
            raise GitCliError(
                GitCliErrorCause.INVALID_CONFIGURATION,
                "Git executable must be absolute",
            )
        try:
            resolved = executable.resolve(strict=True)
        except OSError as error:
            raise GitCliError(GitCliErrorCause.INVALID_CONFIGURATION, str(error)) from error
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise GitCliError(
                GitCliErrorCause.INVALID_CONFIGURATION,
                "Git executable must be an executable file",
            )
        self._executable = resolved
        self._timeout_seconds = _require_timeout(timeout_seconds)
        self._max_output_bytes = _require_output_limit(max_output_bytes)

    def materialize_baseline(
        self,
        source: Path,
        destination: Path,
        baseline_sha: BaselineSha,
    ) -> MaterializedBaseline:
        """Clone and verify one exact baseline without retaining a remote."""
        trusted_source, trusted_destination = self._validate_paths(source, destination)
        baseline_sha = _require_baseline(baseline_sha)

        try:
            with tempfile.TemporaryDirectory(
                prefix=".alicerce-git-control-",
                dir=trusted_destination.parent,
            ) as control_directory:
                control = Path(control_directory)
                hooks = control / "hooks"
                home = control / "home"
                config = control / "config"
                hooks.mkdir()
                home.mkdir()
                config.mkdir()
                environment = self._environment(home, config, hooks)
                parent = trusted_destination.parent

                self._run(
                    (
                        "clone",
                        "--no-local",
                        "--no-hardlinks",
                        "--no-checkout",
                        "--no-tags",
                        str(trusted_source),
                        str(trusted_destination),
                    ),
                    cwd=parent,
                    environment=environment,
                )
                self._run(
                    (
                        "-C",
                        str(trusted_destination),
                        "checkout",
                        "--detach",
                        "--force",
                        baseline_sha.value,
                        "--",
                    ),
                    cwd=parent,
                    environment=environment,
                )
                resolved_head = self._run(
                    (
                        "-C",
                        str(trusted_destination),
                        "rev-parse",
                        "--verify",
                        "HEAD^{commit}",
                    ),
                    cwd=parent,
                    environment=environment,
                ).strip()
                if resolved_head != baseline_sha.value:
                    raise GitCliError(
                        GitCliErrorCause.BASELINE_MISMATCH,
                        "materialized HEAD does not match the requested baseline",
                    )
                self._run(
                    ("-C", str(trusted_destination), "remote", "remove", "origin"),
                    cwd=parent,
                    environment=environment,
                )
        except GitCliError:
            self._discard_partial(trusted_destination)
            raise
        except OSError as error:
            self._discard_partial(trusted_destination)
            raise GitCliError(GitCliErrorCause.COMMAND_FAILED, str(error)) from error

        return MaterializedBaseline(trusted_destination, baseline_sha)

    @staticmethod
    def _validate_paths(source: object, destination: object) -> tuple[Path, Path]:
        source = _require_path(source, name="source")
        destination = _require_path(destination, name="destination")
        if not source.is_absolute() or not destination.is_absolute():
            raise GitCliError(GitCliErrorCause.INVALID_PATH, "paths must be absolute")
        try:
            trusted_source = source.resolve(strict=True)
            trusted_parent = destination.parent.resolve(strict=True)
        except OSError as error:
            raise GitCliError(GitCliErrorCause.INVALID_PATH, str(error)) from error
        trusted_destination = trusted_parent / destination.name
        if not trusted_source.is_dir():
            raise GitCliError(GitCliErrorCause.INVALID_PATH, "source must be a directory")
        if destination.name in {"", ".", ".."}:
            raise GitCliError(GitCliErrorCause.INVALID_PATH, "destination name is invalid")
        if trusted_destination.exists() or trusted_destination.is_symlink():
            raise GitCliError(
                GitCliErrorCause.DESTINATION_EXISTS,
                "destination must not exist",
            )
        if trusted_destination.is_relative_to(trusted_source):
            raise GitCliError(
                GitCliErrorCause.INVALID_PATH,
                "destination must not be inside the source repository",
            )
        return trusted_source, trusted_destination

    @staticmethod
    def _environment(home: Path, config: Path, hooks: Path) -> dict[str, str]:
        return {
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_ASKPASS": "",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_VALUE_0": str(hooks),
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "XDG_CONFIG_HOME": str(config),
        }

    def _run(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> str:
        argv = (str(self._executable), *arguments)
        try:
            process = subprocess.Popen(  # noqa: S603
                argv,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            stdout, _stderr = self._capture_bounded(process)
        except GitCliError:
            raise
        except OSError as error:
            raise GitCliError(
                GitCliErrorCause.COMMAND_FAILED,
                "Git process could not be started",
            ) from error
        if process.returncode != 0:
            raise GitCliError(
                GitCliErrorCause.COMMAND_FAILED,
                f"Git operation exited with status {process.returncode}",
            )
        try:
            return stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise GitCliError(
                GitCliErrorCause.COMMAND_FAILED,
                "Git stdout is not valid UTF-8",
            ) from error

    def _capture_bounded(self, process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + self._timeout_seconds
        stream_targets = {
            cast(BinaryIO, process.stdout): stdout,
            cast(BinaryIO, process.stderr): stderr,
        }
        with selectors.DefaultSelector() as selector:
            for stream in stream_targets:
                selector.register(stream, selectors.EVENT_READ, stream_targets[stream])

            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate(process)
                    raise GitCliError(
                        GitCliErrorCause.TIMEOUT,
                        "Git operation exceeded its fixed deadline",
                    )
                events = selector.select(remaining)
                if not events:
                    self._terminate(process)
                    raise GitCliError(
                        GitCliErrorCause.TIMEOUT,
                        "Git operation exceeded its fixed deadline",
                    )
                for key, _ in events:
                    chunk = os.read(key.fd, min(65_536, self._max_output_bytes + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = cast(bytearray, key.data)
                    target.extend(chunk)
                    if len(stdout) + len(stderr) > self._max_output_bytes:
                        self._terminate(process)
                        raise GitCliError(
                            GitCliErrorCause.OUTPUT_LIMIT,
                            "Git output exceeded the configured capture limit",
                        )
        process.wait()
        return bytes(stdout), bytes(stderr)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            with suppress(ProcessLookupError):
                process.kill()
        process.wait()

    @staticmethod
    def _discard_partial(destination: Path) -> None:
        if destination.exists() and destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
