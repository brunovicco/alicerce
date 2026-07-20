"""Executable contract tests for the provider-neutral command executor port."""

from datetime import UTC, datetime

import pytest

from alicerce.domain.command import (
    CommandAction,
    CommandLimits,
    CommandRequest,
    ExecutableId,
    ExecutionResult,
    ExecutionTermination,
    NetworkPolicy,
    WorkingDirectory,
)
from alicerce.domain.run_identity import BaselineSha, RunId
from alicerce.domain.workspace import WorkspaceId, WorkspaceIdentity
from alicerce.ports.command_executor import (
    CommandExecutionError,
    CommandExecutionErrorCause,
    CommandExecutorPort,
)

NOW = datetime(2026, 7, 20, 17, 0, tzinfo=UTC)


def _request(action: str = "tests") -> CommandRequest:
    return CommandRequest(
        workspace=WorkspaceIdentity(
            WorkspaceId("workspace-executor"),
            RunId("run-executor"),
            BaselineSha("b" * 40),
        ),
        action=CommandAction(action),
        executable=ExecutableId("python"),
        arguments=("-m", "pytest"),
        working_directory=WorkingDirectory("."),
        environment=(),
        network_policy=NetworkPolicy.DENY_ALL,
        limits=CommandLimits(1_000, 100, 32, 32),
    )


class DeterministicExecutor:
    """Test-only structural double with no subprocess behavior."""

    def execute(self, request: CommandRequest) -> ExecutionResult:
        if request.action == CommandAction("denied"):
            raise CommandExecutionError(
                CommandExecutionErrorCause.POLICY_DENIED,
                request.action.value,
            )
        return ExecutionResult(
            request=request,
            termination=ExecutionTermination.EXITED,
            exit_code=0,
            stdout=b"ok",
            stderr=b"",
            started_at=NOW,
            finished_at=NOW,
        )


def test_reference_double_structurally_satisfies_command_executor_port() -> None:
    port: CommandExecutorPort = DeterministicExecutor()
    result = port.execute(_request())
    assert result.request.action == CommandAction("tests")


def test_nonzero_exit_is_an_operational_result_not_a_port_error() -> None:
    request = _request()
    result = ExecutionResult(
        request=request,
        termination=ExecutionTermination.EXITED,
        exit_code=7,
        stdout=b"",
        stderr=b"failed",
        started_at=NOW,
        finished_at=NOW,
    )
    assert result.exit_code == 7
    assert result.termination is ExecutionTermination.EXITED


def test_policy_denial_is_a_typed_preexecution_failure() -> None:
    port: CommandExecutorPort = DeterministicExecutor()
    with pytest.raises(CommandExecutionError) as denied:
        port.execute(_request("denied"))
    assert denied.value.cause is CommandExecutionErrorCause.POLICY_DENIED
    assert str(denied.value) == "policy_denied: denied"


def test_command_execution_error_causes_are_stable() -> None:
    assert tuple(cause.value for cause in CommandExecutionErrorCause) == (
        "policy_denied",
        "workspace_not_found",
        "executable_unavailable",
        "spawn_failed",
        "cleanup_failed",
        "isolation_failure",
    )
