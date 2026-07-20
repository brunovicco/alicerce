"""Integration tests for trusted local command coordination without subprocesses."""

import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from alicerce.adapters.local import command_executor as executor_module
from alicerce.adapters.local.command_executor import LocalCommandExecutor, TrustedExecutable
from alicerce.adapters.local.git_cli import ControlledGitCli
from alicerce.adapters.local.git_workspace import LocalGitWorkspace
from alicerce.adapters.local.process_sandbox import (
    SandboxError,
    SandboxErrorCause,
    SandboxInvocation,
    SandboxResult,
)
from alicerce.domain.command import (
    CommandAction,
    CommandLimits,
    CommandRequest,
    EnvironmentVariable,
    ExecutableId,
    ExecutionTermination,
    NetworkPolicy,
    WorkingDirectory,
)
from alicerce.domain.command_policy import (
    AuthorizedCommand,
    CommandAuthorizationError,
    CommandAuthorizationErrorCause,
    CommandPolicy,
    CommandRule,
    authorize_command,
)
from alicerce.domain.contracts import Actions
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)
from alicerce.domain.workspace import WorkspaceId, WorkspaceIdentity
from alicerce.ports.command_executor import (
    CommandExecutionError,
    CommandExecutionErrorCause,
    CommandExecutorPort,
)

NOW = datetime(2026, 7, 20, 19, 0, tzinfo=UTC)


class OneWorkspaceId:
    """Deterministic workspace capability generator for integration tests."""

    def new_workspace_id(self) -> WorkspaceId:
        return WorkspaceId("workspace-command")


class RecordingSandbox:
    """Test-only backend recording trusted invocations without spawning."""

    def __init__(
        self,
        *,
        supported: bool = True,
        result: SandboxResult | object | None = None,
        error: SandboxError | None = None,
        mutation: Callable[[SandboxInvocation], None] | None = None,
    ) -> None:
        self.supported = supported
        self.result = result
        self.error = error
        self.mutation = mutation
        self.support_calls = 0
        self.execute_calls = 0
        self.invocations: list[SandboxInvocation] = []

    def supports(self, network_policy: NetworkPolicy) -> bool:
        assert network_policy is NetworkPolicy.DENY_ALL
        self.support_calls += 1
        return self.supported

    def execute(self, invocation: SandboxInvocation) -> SandboxResult:
        self.execute_calls += 1
        self.invocations.append(invocation)
        if self.mutation is not None:
            self.mutation(invocation)
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return cast(SandboxResult, self.result)
        return SandboxResult(
            termination=ExecutionTermination.EXITED,
            exit_code=0,
            stdout=b"passed",
            stderr=b"",
            started_at=NOW,
            finished_at=NOW,
        )


def _git() -> Path:
    executable = shutil.which("git")
    assert executable is not None
    return Path(executable).resolve()


def _run_git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603
        (str(_git()), "-C", str(repository), *arguments),
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={"HOME": str(repository.parent), "LC_ALL": "C.UTF-8"},
    )
    return completed.stdout.decode().strip()


def _source_repository(tmp_path: Path) -> tuple[Path, BaselineSha]:
    source = tmp_path / "source"
    source.mkdir()
    _run_git(source, "init", "--initial-branch=main")
    _run_git(source, "config", "user.name", "Alicerce Tests")
    _run_git(source, "config", "user.email", "tests@alicerce.invalid")
    (source / "payload.txt").write_text("baseline\n", encoding="utf-8")
    _run_git(source, "add", "payload.txt")
    _run_git(source, "commit", "-m", "baseline")
    return source, BaselineSha(_run_git(source, "rev-parse", "HEAD"))


def _identity(baseline: BaselineSha, run_id: str = "run-command") -> RunIdentity:
    return RunIdentity(
        run_id=RunId(run_id),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=baseline,
        policy_hash=PolicyHash("c" * 64),
        created_at=NOW,
    )


def _workspace(
    tmp_path: Path,
) -> tuple[LocalGitWorkspace, RunIdentity, WorkspaceIdentity, Path]:
    source, baseline = _source_repository(tmp_path)
    root = tmp_path / "workspaces"
    protected = tmp_path / "protected"
    root.mkdir()
    protected.mkdir()
    adapter = LocalGitWorkspace(
        source_repository=source,
        workspace_root=root,
        protected_roots=(protected,),
        git=ControlledGitCli(_git()),
        id_generator=OneWorkspaceId(),
    )
    identity = _identity(baseline)
    workspace = adapter.prepare(identity)
    return adapter, identity, workspace, root / workspace.workspace_id.value


def _executable(tmp_path: Path, name: str = "python") -> TrustedExecutable:
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    path = tools / name
    path.write_bytes(b"trusted executable\n")
    path.chmod(0o755)
    return TrustedExecutable(ExecutableId(name), path)


def _authorized(
    identity: RunIdentity,
    workspace: WorkspaceIdentity,
    *,
    executable: str = "python",
    working_directory: str = ".",
    environment: tuple[EnvironmentVariable, ...] = (EnvironmentVariable("LANG", "C.UTF-8"),),
) -> AuthorizedCommand:
    request = CommandRequest(
        run_identity=identity,
        workspace=workspace,
        action=CommandAction("tests"),
        executable=ExecutableId(executable),
        arguments=("-m", "pytest"),
        working_directory=WorkingDirectory(working_directory),
        environment=environment,
        network_policy=NetworkPolicy.DENY_ALL,
        limits=CommandLimits(1_000, 100, 64, 64),
    )
    rule = CommandRule(
        action=request.action,
        executable=request.executable,
        arguments=request.arguments,
        working_directory=request.working_directory,
        environment_names=tuple(entry.name for entry in request.environment),
        network_policy=request.network_policy,
        max_limits=request.limits,
    )
    policy = CommandPolicy(
        policy_hash=identity.policy_hash,
        actions=Actions(allowed=("tests",), denied=()),
        rules=(rule,),
    )
    return authorize_command(request, policy)


def _executor(
    workspace: LocalGitWorkspace,
    executable: TrustedExecutable,
    sandbox: RecordingSandbox,
) -> LocalCommandExecutor:
    return LocalCommandExecutor(
        workspace=workspace,
        executables=(executable,),
        sandbox=sandbox,
    )


def test_adapter_satisfies_port_and_builds_minimal_shell_free_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity, handle, checkout = _workspace(tmp_path)
    executable = _executable(tmp_path)
    sandbox = RecordingSandbox()
    monkeypatch.setenv("ALICERCE_SECRET", "must-not-be-inherited")
    port: CommandExecutorPort = _executor(workspace, executable, sandbox)

    result = port.execute(_authorized(identity, handle))

    assert result.exit_code == 0
    assert result.stdout == b"passed"
    assert sandbox.execute_calls == 1
    invocation = sandbox.invocations[0]
    assert invocation.executable == executable.path
    assert invocation.arguments == ("-m", "pytest")
    assert invocation.working_directory == checkout
    assert invocation.environment == (EnvironmentVariable("LANG", "C.UTF-8"),)
    assert "ALICERCE_SECRET" not in {entry.name for entry in invocation.environment}


def test_nested_working_directory_is_resolved_inside_workspace(tmp_path: Path) -> None:
    workspace, identity, handle, checkout = _workspace(tmp_path)
    (checkout / "project" / "src").mkdir(parents=True)
    executable = _executable(tmp_path)
    sandbox = RecordingSandbox()

    _executor(workspace, executable, sandbox).execute(
        _authorized(identity, handle, working_directory="project/src")
    )

    assert sandbox.invocations[0].working_directory == checkout / "project" / "src"


def test_raw_request_is_rejected_before_sandbox_invocation(tmp_path: Path) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    executable = _executable(tmp_path)
    sandbox = RecordingSandbox()
    command = _authorized(identity, handle)

    with pytest.raises(TypeError, match="command must be AuthorizedCommand"):
        _executor(workspace, executable, sandbox).execute(command.request)  # type: ignore[arg-type]
    assert sandbox.support_calls == 0
    assert sandbox.execute_calls == 0


def test_reauthorization_denial_precedes_sandbox_capability_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    executable = _executable(tmp_path)
    sandbox = RecordingSandbox()

    def deny(request: CommandRequest, policy: CommandPolicy) -> AuthorizedCommand:
        raise CommandAuthorizationError(
            CommandAuthorizationErrorCause.ACTION_DENIED,
            request.action.value,
        )

    monkeypatch.setattr(executor_module, "authorize_command", deny)
    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, executable, sandbox).execute(_authorized(identity, handle))
    assert captured.value.cause is CommandExecutionErrorCause.POLICY_DENIED
    assert sandbox.support_calls == 0
    assert sandbox.execute_calls == 0


def test_changed_reauthorization_result_fails_before_sandbox_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    executable = _executable(tmp_path)
    sandbox = RecordingSandbox()
    original = _authorized(identity, handle)
    replacement = _authorized(identity, handle, environment=())

    def replace_authorization(
        request: CommandRequest,
        policy: CommandPolicy,
    ) -> AuthorizedCommand:
        return replacement

    monkeypatch.setattr(executor_module, "authorize_command", replace_authorization)
    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, executable, sandbox).execute(original)
    assert captured.value.cause is CommandExecutionErrorCause.POLICY_DENIED
    assert sandbox.support_calls == 0
    assert sandbox.execute_calls == 0


def test_backend_without_network_enforcement_fails_before_execute(tmp_path: Path) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    sandbox = RecordingSandbox(supported=False)

    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, _executable(tmp_path), sandbox).execute(_authorized(identity, handle))
    assert captured.value.cause is CommandExecutionErrorCause.POLICY_DENIED
    assert sandbox.support_calls == 1
    assert sandbox.execute_calls == 0


def test_unknown_executable_fails_before_sandbox_check(tmp_path: Path) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    sandbox = RecordingSandbox()

    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, _executable(tmp_path), sandbox).execute(
            _authorized(identity, handle, executable="uv")
        )
    assert captured.value.cause is CommandExecutionErrorCause.EXECUTABLE_UNAVAILABLE
    assert sandbox.support_calls == 0
    assert sandbox.execute_calls == 0


@pytest.mark.parametrize("change", ["content", "permission", "missing"])
def test_changed_executable_fails_before_backend_execute(tmp_path: Path, change: str) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    executable = _executable(tmp_path)
    sandbox = RecordingSandbox()
    if change == "content":
        executable.path.write_bytes(b"changed\n")
    elif change == "permission":
        executable.path.chmod(0o644)
    else:
        executable.path.unlink()

    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, executable, sandbox).execute(_authorized(identity, handle))
    assert captured.value.cause in {
        CommandExecutionErrorCause.EXECUTABLE_UNAVAILABLE,
        CommandExecutionErrorCause.ISOLATION_FAILURE,
    }
    assert sandbox.execute_calls == 0


def test_executable_changed_by_backend_is_detected_before_return(tmp_path: Path) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    executable = _executable(tmp_path)

    def replace_executable(invocation: SandboxInvocation) -> None:
        invocation.executable.write_bytes(b"replaced\n")

    sandbox = RecordingSandbox(mutation=replace_executable)
    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, executable, sandbox).execute(_authorized(identity, handle))
    assert captured.value.cause is CommandExecutionErrorCause.ISOLATION_FAILURE
    assert sandbox.execute_calls == 1


@pytest.mark.parametrize("kind", ["missing", "symlink", "file"])
def test_invalid_working_directory_fails_before_backend_execute(
    tmp_path: Path,
    kind: str,
) -> None:
    workspace, identity, handle, checkout = _workspace(tmp_path)
    if kind == "symlink":
        (checkout / "real").mkdir()
        (checkout / "target").symlink_to("real", target_is_directory=True)
    elif kind == "file":
        (checkout / "target").write_text("not a directory", encoding="utf-8")
    sandbox = RecordingSandbox()

    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, _executable(tmp_path), sandbox).execute(
            _authorized(identity, handle, working_directory="target")
        )
    assert captured.value.cause is CommandExecutionErrorCause.ISOLATION_FAILURE
    assert sandbox.execute_calls == 0


def test_unknown_workspace_maps_to_stable_port_cause(tmp_path: Path) -> None:
    workspace, identity, _, _ = _workspace(tmp_path)
    missing = WorkspaceIdentity(
        WorkspaceId("missing-workspace"),
        identity.run_id,
        identity.baseline_sha,
    )
    sandbox = RecordingSandbox()

    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, _executable(tmp_path), sandbox).execute(_authorized(identity, missing))
    assert captured.value.cause is CommandExecutionErrorCause.WORKSPACE_NOT_FOUND
    assert sandbox.execute_calls == 0


def test_workspace_escape_created_by_backend_fails_during_postvalidation(
    tmp_path: Path,
) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    def create_escape(invocation: SandboxInvocation) -> None:
        (invocation.working_directory / "escape").symlink_to(
            outside,
            target_is_directory=True,
        )

    sandbox = RecordingSandbox(mutation=create_escape)
    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, _executable(tmp_path), sandbox).execute(_authorized(identity, handle))
    assert captured.value.cause is CommandExecutionErrorCause.ISOLATION_FAILURE
    assert sandbox.execute_calls == 1


@pytest.mark.parametrize(
    ("sandbox_cause", "port_cause"),
    [
        (SandboxErrorCause.SPAWN_FAILED, CommandExecutionErrorCause.SPAWN_FAILED),
        (SandboxErrorCause.CLEANUP_FAILED, CommandExecutionErrorCause.CLEANUP_FAILED),
        (
            SandboxErrorCause.ISOLATION_FAILURE,
            CommandExecutionErrorCause.ISOLATION_FAILURE,
        ),
    ],
)
def test_sandbox_errors_map_without_output_string_matching(
    tmp_path: Path,
    sandbox_cause: SandboxErrorCause,
    port_cause: CommandExecutionErrorCause,
) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    sandbox = RecordingSandbox(error=SandboxError(sandbox_cause, "injected"))

    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, _executable(tmp_path), sandbox).execute(_authorized(identity, handle))
    assert captured.value.cause is port_cause
    assert str(captured.value).endswith("process sandbox failed")


@pytest.mark.parametrize(
    "result",
    [
        object(),
        SandboxResult(
            ExecutionTermination.EXITED,
            0,
            b"x" * 65,
            b"",
            NOW,
            NOW,
        ),
    ],
)
def test_invalid_sandbox_result_fails_closed(tmp_path: Path, result: object) -> None:
    workspace, identity, handle, _ = _workspace(tmp_path)
    sandbox = RecordingSandbox(result=result)

    with pytest.raises(CommandExecutionError) as captured:
        _executor(workspace, _executable(tmp_path), sandbox).execute(_authorized(identity, handle))
    assert captured.value.cause is CommandExecutionErrorCause.ISOLATION_FAILURE


def test_trusted_executable_rejects_unsafe_configuration(tmp_path: Path) -> None:
    relative = Path("tool")
    with pytest.raises(TypeError):
        TrustedExecutable(object(), tmp_path)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        TrustedExecutable(ExecutableId("tool"), object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="absolute"):
        TrustedExecutable(ExecutableId("tool"), relative)
    with pytest.raises(ValueError, match="unavailable"):
        TrustedExecutable(ExecutableId("tool"), tmp_path / "missing")

    target = tmp_path / "target"
    target.write_text("tool", encoding="utf-8")
    target.chmod(0o755)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="not a symlink"):
        TrustedExecutable(ExecutableId("tool"), link)

    target.chmod(0o644)
    with pytest.raises(ValueError, match="executable regular file"):
        TrustedExecutable(ExecutableId("tool"), target)


@pytest.mark.parametrize(
    "case",
    ["workspace", "tuple", "entry", "duplicate", "sandbox"],
)
def test_executor_rejects_invalid_collaborator_configuration(
    tmp_path: Path,
    case: str,
) -> None:
    workspace, _, _, _ = _workspace(tmp_path)
    executable = _executable(tmp_path)
    sandbox = RecordingSandbox()
    with pytest.raises((TypeError, ValueError)):
        if case == "workspace":
            LocalCommandExecutor(
                workspace=object(),  # type: ignore[arg-type]
                executables=(executable,),
                sandbox=sandbox,
            )
        elif case == "tuple":
            LocalCommandExecutor(
                workspace=workspace,
                executables=[executable],  # type: ignore[arg-type]
                sandbox=sandbox,
            )
        elif case == "entry":
            LocalCommandExecutor(
                workspace=workspace,
                executables=(object(),),  # type: ignore[arg-type]
                sandbox=sandbox,
            )
        elif case == "duplicate":
            LocalCommandExecutor(
                workspace=workspace,
                executables=(executable, executable),
                sandbox=sandbox,
            )
        else:
            LocalCommandExecutor(
                workspace=workspace,
                executables=(executable,),
                sandbox=object(),  # type: ignore[arg-type]
            )


def test_executable_registry_requires_sorted_identifiers(tmp_path: Path) -> None:
    workspace, _, _, _ = _workspace(tmp_path)
    python = _executable(tmp_path, "python")
    uv = _executable(tmp_path, "uv")
    with pytest.raises(ValueError, match="sorted"):
        LocalCommandExecutor(
            workspace=workspace,
            executables=(uv, python),
            sandbox=RecordingSandbox(),
        )


def test_adapter_private_sandbox_errors_expose_stable_values() -> None:
    error = SandboxError(SandboxErrorCause.CLEANUP_FAILED, "injected")
    assert error.cause is SandboxErrorCause.CLEANUP_FAILED
    assert str(error) == "cleanup_failed: injected"
    assert tuple(cause.value for cause in SandboxErrorCause) == (
        "spawn_failed",
        "cleanup_failed",
        "isolation_failure",
    )
