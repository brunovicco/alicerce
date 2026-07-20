"""Tests for the Linux bubblewrap process sandbox adapter."""

import os
import shutil
import signal
import subprocess
import sys
from datetime import UTC
from pathlib import Path
from typing import cast

import pytest

from alicerce.adapters.local import linux_process_sandbox as sandbox_module
from alicerce.adapters.local.linux_process_sandbox import LinuxProcessSandboxBackend
from alicerce.adapters.local.process_sandbox import (
    SandboxError,
    SandboxErrorCause,
    SandboxInvocation,
)
from alicerce.domain.command import (
    CommandLimits,
    EnvironmentVariable,
    ExecutionTermination,
    NetworkPolicy,
)

_HOST_PLATFORM = sys.platform


@pytest.fixture(autouse=True)
def _linux_adapter_contract(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the Linux adapter deterministically on every development host."""
    monkeypatch.setattr(sys, "platform", "linux")
    if _HOST_PLATFORM != "linux":
        host_killpg = os.killpg

        def portable_killpg(pid: int, sent_signal: signal.Signals) -> None:
            try:
                host_killpg(pid, sent_signal)
            except PermissionError:
                os.kill(pid, sent_signal)

        monkeypatch.setattr(sandbox_module.os, "killpg", portable_killpg)


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_bubblewrap(tmp_path: Path, *, probe_exit: int = 0) -> Path:
    return _write_executable(
        tmp_path / "bwrap",
        f"""
target=""
working="/"
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
    case "$1" in
        --ro-bind)
            if [ "$3" = "/alicerce/executable" ]; then target="$2"; fi
            shift 3
            ;;
        --chdir)
            working="$2"
            shift 2
            ;;
        --setenv)
            export "$2=$3"
            shift 3
            ;;
        --proc|--dev|--dir)
            shift 2
            ;;
        --symlink|--bind)
            shift 3
            ;;
        *)
            shift
            ;;
    esac
done
shift
if [ "$1" = "/usr/bin/true" ]; then exit {probe_exit}; fi
if [ "$1" = "/alicerce/executable" ]; then shift; set -- "$target" "$@"; fi
cd "$working"
exec "$@"
""",
    )


def _invocation(
    tmp_path: Path,
    body: str,
    *,
    arguments: tuple[str, ...] = (),
    timeout_ms: int = 2_000,
    grace_ms: int = 100,
    stdout_max: int = 4_096,
    stderr_max: int = 4_096,
    environment: tuple[EnvironmentVariable, ...] = (),
) -> SandboxInvocation:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    working = workspace / "nested"
    working.mkdir(exist_ok=True)
    executable = _write_executable(tmp_path / "command", body)
    return SandboxInvocation(
        executable=executable,
        arguments=arguments,
        workspace_root=workspace,
        working_directory=working,
        environment=environment,
        network_policy=NetworkPolicy.DENY_ALL,
        limits=CommandLimits(timeout_ms, grace_ms, stdout_max, stderr_max),
    )


def test_constructor_requires_linux_and_a_pinned_absolute_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _fake_bubblewrap(tmp_path)
    with pytest.raises(TypeError, match="bubblewrap_path"):
        LinuxProcessSandboxBackend(cast(object, str(executable)))
    with pytest.raises(ValueError, match="absolute"):
        LinuxProcessSandboxBackend(Path("bwrap"))
    link = tmp_path / "link"
    link.symlink_to(executable)
    with pytest.raises(ValueError, match="not a symlink"):
        LinuxProcessSandboxBackend(link)
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(OSError, match="requires Linux"):
        LinuxProcessSandboxBackend(executable)


def test_constructor_rejects_missing_and_non_executable_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unavailable"):
        LinuxProcessSandboxBackend(tmp_path / "missing")
    plain = tmp_path / "plain"
    plain.write_text("plain", encoding="utf-8")
    with pytest.raises(ValueError, match="executable regular file"):
        LinuxProcessSandboxBackend(plain)


def test_supports_requires_successful_deny_all_probe(tmp_path: Path) -> None:
    supported = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))
    assert supported.supports(NetworkPolicy.DENY_ALL)
    unavailable = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path / "other", probe_exit=9))
    assert not unavailable.supports(NetworkPolicy.DENY_ALL)
    assert not supported.supports(cast(NetworkPolicy, object()))


def test_supports_fails_closed_on_probe_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))

    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise OSError("injected")

    monkeypatch.setattr(subprocess, "run", fail)
    assert not backend.supports(NetworkPolicy.DENY_ALL)


def test_execute_captures_explicit_environment_working_directory_and_exit(
    tmp_path: Path,
) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))
    invocation = _invocation(
        tmp_path,
        'printf "%s|%s|%s" "$VALUE" "$PWD" "$1"; printf "warning" >&2; exit 7',
        arguments=("argument",),
        environment=(EnvironmentVariable("VALUE", "explicit"),),
    )
    result = backend.execute(invocation)
    assert result.termination is ExecutionTermination.EXITED
    assert result.exit_code == 7
    assert result.stdout == f"explicit|{invocation.working_directory}|argument".encode()
    assert result.stderr == b"warning"
    assert result.started_at.tzinfo is UTC
    assert result.finished_at >= result.started_at


def test_execute_enforces_stdout_and_stderr_limits(tmp_path: Path) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))
    stdout = backend.execute(_invocation(tmp_path, "printf 123456789", stdout_max=4, stderr_max=20))
    assert stdout.termination is ExecutionTermination.OUTPUT_LIMIT
    assert stdout.exit_code is None
    assert stdout.stdout == b"1234"

    stderr_path = tmp_path / "stderr-case"
    stderr_path.mkdir()
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(stderr_path))
    stderr = backend.execute(
        _invocation(stderr_path, "printf abcdefghi >&2", stdout_max=20, stderr_max=3)
    )
    assert stderr.termination is ExecutionTermination.OUTPUT_LIMIT
    assert stderr.stderr == b"abc"


def test_execute_enforces_timeout_and_terminates_process_group(tmp_path: Path) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))
    result = backend.execute(_invocation(tmp_path, "sleep 5", timeout_ms=30, grace_ms=30))
    assert result.termination is ExecutionTermination.TIMED_OUT
    assert result.exit_code is None


def test_execute_rejects_invalid_invocation_and_unavailable_isolation(tmp_path: Path) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path, probe_exit=1))
    with pytest.raises(TypeError, match="SandboxInvocation"):
        backend.execute(object())
    with pytest.raises(SandboxError) as captured:
        backend.execute(_invocation(tmp_path, "exit 0"))
    assert captured.value.cause is SandboxErrorCause.ISOLATION_FAILURE


def test_execute_maps_spawn_and_capture_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))
    invocation = _invocation(tmp_path, "/usr/bin/sleep 5")
    original_popen = subprocess.Popen

    def supported(
        self: LinuxProcessSandboxBackend,
        policy: NetworkPolicy,
    ) -> bool:
        del self
        return policy is NetworkPolicy.DENY_ALL

    monkeypatch.setattr(
        LinuxProcessSandboxBackend,
        "supports",
        supported,
    )

    def fail_spawn(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        raise OSError("injected")

    monkeypatch.setattr(subprocess, "Popen", fail_spawn)
    with pytest.raises(SandboxError) as spawned:
        backend.execute(invocation)
    assert spawned.value.cause is SandboxErrorCause.SPAWN_FAILED

    monkeypatch.setattr(subprocess, "Popen", original_popen)

    def fail_capture(self: object) -> object:
        del self
        raise OSError("injected")

    monkeypatch.setattr(sandbox_module._Capture, "__enter__", fail_capture)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(SandboxError) as captured:
        backend.execute(invocation)
    assert captured.value.cause is SandboxErrorCause.CLEANUP_FAILED


def test_execute_detects_changed_bubblewrap(tmp_path: Path) -> None:
    executable = _fake_bubblewrap(tmp_path)
    backend = LinuxProcessSandboxBackend(executable)
    executable.write_text("changed", encoding="utf-8")
    with pytest.raises(SandboxError) as captured:
        backend.supports(NetworkPolicy.DENY_ALL)
    assert captured.value.cause is SandboxErrorCause.ISOLATION_FAILURE


def test_verify_maps_disappearing_bubblewrap(tmp_path: Path) -> None:
    executable = _fake_bubblewrap(tmp_path)
    backend = LinuxProcessSandboxBackend(executable)
    executable.unlink()
    with pytest.raises(SandboxError) as captured:
        backend.supports(NetworkPolicy.DENY_ALL)
    assert captured.value.cause is SandboxErrorCause.ISOLATION_FAILURE


def test_capture_rejects_missing_pipe() -> None:
    class MissingPipeProcess:
        stdout = None
        stderr = None

    capture_context = sandbox_module._Capture(  # pyright: ignore[reportPrivateUsage]
        cast(subprocess.Popen[bytes], MissingPipeProcess())
    )
    try:
        with pytest.raises(SandboxError) as error:
            capture_context.__enter__()
        assert error.value.cause is SandboxErrorCause.SPAWN_FAILED
    finally:
        capture_context.selector.close()


def test_capture_retries_a_nonblocking_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))
    invocation = _invocation(tmp_path, "printf ready")
    original_enter = sandbox_module._Capture.__enter__  # pyright: ignore[reportPrivateUsage]
    original_read = sandbox_module.os.read
    calls = 0

    def enter_with_one_block(
        capture: sandbox_module._Capture,  # pyright: ignore[reportPrivateUsage]
    ) -> sandbox_module._Capture:  # pyright: ignore[reportPrivateUsage]
        result = original_enter(capture)

        def read(fd: int, length: int) -> bytes:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise BlockingIOError
            return original_read(fd, length)

        monkeypatch.setattr(sandbox_module.os, "read", read)
        return result

    monkeypatch.setattr(sandbox_module._Capture, "__enter__", enter_with_one_block)  # pyright: ignore[reportPrivateUsage]
    result = backend.execute(invocation)
    assert result.stdout == b"ready"
    assert calls >= 2


def test_process_tree_cleanup_escalates_and_maps_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubbornProcess:
        pid = 12345
        waits = 0

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("test", 0.01)
            return -9

    process = StubbornProcess()
    signals: list[signal.Signals] = []

    def record_killpg(pid: int, sent_signal: signal.Signals) -> None:
        assert pid == process.pid
        signals.append(sent_signal)

    monkeypatch.setattr(sandbox_module.os, "killpg", record_killpg)
    LinuxProcessSandboxBackend._terminate_tree(  # pyright: ignore[reportPrivateUsage]
        cast(subprocess.Popen[bytes], process),
        10,
    )
    assert signals == [signal.SIGTERM, signal.SIGKILL]

    def fail_killpg(pid: int, sent_signal: signal.Signals) -> None:
        del pid, sent_signal
        raise OSError("injected")

    monkeypatch.setattr(sandbox_module.os, "killpg", fail_killpg)
    with pytest.raises(SandboxError) as captured:
        LinuxProcessSandboxBackend._terminate_tree(  # pyright: ignore[reportPrivateUsage]
            cast(subprocess.Popen[bytes], StubbornProcess()),
            10,
        )
    assert captured.value.cause is SandboxErrorCause.CLEANUP_FAILED


def test_command_contains_only_explicit_mounts_and_no_shell(tmp_path: Path) -> None:
    backend = LinuxProcessSandboxBackend(_fake_bubblewrap(tmp_path))
    invocation = _invocation(tmp_path, "exit 0")
    command = backend._build_command(invocation)  # pyright: ignore[reportPrivateUsage]
    assert "--unshare-net" in command
    assert "--unshare-pid" in command
    assert "--clearenv" in command
    triples = tuple(zip(command, command[1:], command[2:], strict=False))
    assert ("--ro-bind", "/", "/") not in triples
    assert "--bind" in command
    assert str(invocation.workspace_root) in command
    assert command[-1] == "/alicerce/executable"
    assert not ({"sh", "bash", "-c"} & set(command))


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is unavailable")
def test_real_bubblewrap_capability_probe_is_fail_closed() -> None:
    path = Path(cast(str, shutil.which("bwrap"))).resolve()
    if path.is_symlink():
        pytest.skip("bubblewrap resolves through a symlink")
    backend = LinuxProcessSandboxBackend(path)
    supported = backend.supports(NetworkPolicy.DENY_ALL)
    assert isinstance(supported, bool)
