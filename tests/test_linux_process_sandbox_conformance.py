"""Adversarial conformance tests for the real Linux bubblewrap sandbox."""

import json
import os
import shutil
import signal
import socket
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

import pytest

from alicerce.adapters.local.linux_process_sandbox import LinuxProcessSandboxBackend
from alicerce.adapters.local.process_sandbox import SandboxInvocation
from alicerce.domain.command import (
    CommandLimits,
    EnvironmentVariable,
    ExecutionTermination,
    NetworkPolicy,
)

_CONFORMANCE_ENABLED = os.environ.get("ALICERCE_LINUX_SANDBOX_CONFORMANCE") == "1"
_SYSTEM_PYTHON = Path("/usr/bin/python3")
pytestmark = pytest.mark.skipif(
    not _CONFORMANCE_ENABLED,
    reason="real Linux sandbox conformance profile is not enabled",
)


@pytest.fixture(scope="module")
def real_backend() -> LinuxProcessSandboxBackend:
    """Require the configured Linux profile without a permissive skip."""
    if sys.platform != "linux":
        pytest.fail("Linux sandbox conformance requires a Linux runner")
    discovered = shutil.which("bwrap")
    if discovered is None:
        pytest.fail("required bubblewrap executable is unavailable")
    path = Path(discovered)
    if path.is_symlink():
        pytest.fail("required bubblewrap executable must not be a symlink")
    if not _SYSTEM_PYTHON.is_file() or not os.access(_SYSTEM_PYTHON, os.X_OK):
        pytest.fail("required system Python executable is unavailable")
    return LinuxProcessSandboxBackend(path.resolve(strict=True))


def _invocation(
    tmp_path: Path,
    code: str,
    *,
    arguments: tuple[str, ...] = (),
    environment: tuple[EnvironmentVariable, ...] = (),
    timeout_ms: int = 2_000,
    grace_ms: int = 200,
) -> SandboxInvocation:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    working = workspace / "nested"
    working.mkdir()
    return SandboxInvocation(
        executable=_SYSTEM_PYTHON.resolve(strict=True),
        arguments=("-I", "-c", code, *arguments),
        workspace_root=workspace,
        working_directory=working,
        environment=environment,
        network_policy=NetworkPolicy.DENY_ALL,
        limits=CommandLimits(timeout_ms, grace_ms, 16_384, 16_384),
    )


def test_required_namespace_capability_is_available(
    real_backend: LinuxProcessSandboxBackend,
) -> None:
    """The configured job must fail when the production probe cannot isolate."""
    assert real_backend.supports(NetworkPolicy.DENY_ALL), (
        "configured Linux runner cannot create the required bubblewrap namespaces"
    )


def test_network_namespace_cannot_reach_host_listener(
    real_backend: LinuxProcessSandboxBackend,
    tmp_path: Path,
) -> None:
    """The sandbox network namespace cannot connect to a host loopback listener."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        _host, port = cast(tuple[str, int], listener.getsockname())
        code = """
import socket
import sys

try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=0.5):
        raise SystemExit(41)
except OSError:
    print("network-denied")
"""
        result = real_backend.execute(_invocation(tmp_path, code, arguments=(str(port),)))

    assert result.termination is ExecutionTermination.EXITED
    assert result.exit_code == 0
    assert result.stdout == b"network-denied\n"


def test_workspace_is_the_only_writable_filesystem_area(
    real_backend: LinuxProcessSandboxBackend,
    tmp_path: Path,
) -> None:
    """Only the mapped candidate workspace accepts ordinary file writes."""
    outside = tmp_path / "outside-host.txt"
    code = """
import json
import sys
from pathlib import Path

targets = {
    "workspace": Path("/workspace/allowed.txt"),
    "system": Path("/usr/alicerce-forbidden"),
    "private": Path("/alicerce/forbidden"),
    "temporary": Path("/tmp/alicerce-forbidden"),
    "host": Path(sys.argv[1]),
}
results = {}
for name, path in targets.items():
    try:
        path.write_text(name, encoding="utf-8")
    except OSError:
        results[name] = False
    else:
        results[name] = True
print(json.dumps(results, sort_keys=True))
"""
    invocation = _invocation(tmp_path, code, arguments=(str(outside),))
    result = real_backend.execute(invocation)

    assert result.termination is ExecutionTermination.EXITED
    assert result.exit_code == 0
    observed = cast(dict[str, bool], json.loads(result.stdout))
    assert observed == {
        "host": False,
        "private": False,
        "system": False,
        "temporary": False,
        "workspace": True,
    }
    assert (invocation.workspace_root / "allowed.txt").read_text(encoding="utf-8") == "workspace"
    assert not outside.exists()


def test_candidate_receives_only_explicit_environment(
    real_backend: LinuxProcessSandboxBackend,
    tmp_path: Path,
) -> None:
    """No host or runner environment entry reaches the candidate."""
    code = """
import json
import os

print(json.dumps(dict(os.environ), sort_keys=True))
"""
    explicit = (
        EnvironmentVariable("ALICERCE_ALLOWED", "yes"),
        EnvironmentVariable("LC_ALL", "C.UTF-8"),
    )
    result = real_backend.execute(_invocation(tmp_path, code, environment=explicit))

    assert result.termination is ExecutionTermination.EXITED
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "ALICERCE_ALLOWED": "yes",
        "LC_ALL": "C.UTF-8",
    }


def test_real_timeout_returns_typed_termination(
    real_backend: LinuxProcessSandboxBackend,
    tmp_path: Path,
) -> None:
    """A real long-running candidate returns the bounded typed timeout."""
    started = time.monotonic()
    result = real_backend.execute(
        _invocation(tmp_path, "import time; time.sleep(10)", timeout_ms=150, grace_ms=100)
    )
    elapsed = time.monotonic() - started

    assert result.termination is ExecutionTermination.TIMED_OUT
    assert result.exit_code is None
    assert elapsed < 2.0


def test_timeout_terminates_resistant_descendants(
    real_backend: LinuxProcessSandboxBackend,
    tmp_path: Path,
) -> None:
    """A descendant that ignores SIGTERM cannot outlive sandbox cleanup."""
    child_code = """
import os
import signal
import sys
import time
from pathlib import Path

signal.signal(signal.SIGTERM, signal.SIG_IGN)
heartbeat = Path(sys.argv[1])
late = Path(sys.argv[2])
host_pid = Path(sys.argv[3])
status = Path("/proc/self/status").read_text(encoding="utf-8")
nspid = next(line for line in status.splitlines() if line.startswith("NSpid:"))
host_pid.write_text(nspid.split()[1], encoding="utf-8")
started = time.monotonic()
while True:
    with heartbeat.open("ab", buffering=0) as stream:
        stream.write(b"x")
        os.fsync(stream.fileno())
    if time.monotonic() - started >= 0.6 and not late.exists():
        late.write_text("descendant-survived", encoding="utf-8")
    time.sleep(0.02)
"""
    parent_code = """
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen(
    [sys.executable, "-I", "-c", sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]]
)
deadline = time.monotonic() + 2
while not Path(sys.argv[2]).exists():
    if time.monotonic() >= deadline:
        raise SystemExit(42)
    time.sleep(0.01)
time.sleep(10)
"""
    invocation = _invocation(
        tmp_path,
        parent_code,
        arguments=(
            child_code,
            "/workspace/heartbeat",
            "/workspace/late-marker",
            "/workspace/descendant-host-pid",
        ),
        timeout_ms=300,
        grace_ms=100,
    )
    result = real_backend.execute(invocation)
    heartbeat = invocation.workspace_root / "heartbeat"
    late_marker = invocation.workspace_root / "late-marker"
    host_pid_file = invocation.workspace_root / "descendant-host-pid"

    assert result.termination is ExecutionTermination.TIMED_OUT
    assert result.exit_code is None
    assert heartbeat.exists()
    size_after_return = heartbeat.stat().st_size
    time.sleep(0.7)
    size_after_wait = heartbeat.stat().st_size

    descendant_survived = size_after_wait != size_after_return or late_marker.exists()
    if descendant_survived and host_pid_file.exists():
        host_pid = int(host_pid_file.read_text(encoding="utf-8"))
        with suppress(ProcessLookupError):
            os.kill(host_pid, signal.SIGKILL)

    assert size_after_wait == size_after_return
    assert not late_marker.exists()
