"""Tests for immutable controlled-command values and result invariants."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from alicerce.domain.command import (
    CommandAction,
    CommandLimits,
    CommandRequest,
    EnvironmentVariable,
    ExecutableId,
    ExecutionResult,
    ExecutionTermination,
    NetworkPolicy,
    WorkingDirectory,
)
from alicerce.domain.run_identity import BaselineSha, RunId
from alicerce.domain.workspace import WorkspaceId, WorkspaceIdentity

STARTED = datetime(2026, 7, 20, 16, 0, tzinfo=UTC)
FINISHED = datetime(2026, 7, 20, 16, 0, 1, tzinfo=UTC)


def _workspace() -> WorkspaceIdentity:
    return WorkspaceIdentity(
        workspace_id=WorkspaceId("workspace-command"),
        run_id=RunId("run-command"),
        baseline_sha=BaselineSha("b" * 40),
    )


def _limits() -> CommandLimits:
    return CommandLimits(
        timeout_ms=30_000,
        termination_grace_ms=2_000,
        stdout_max_bytes=16,
        stderr_max_bytes=16,
    )


def _request() -> CommandRequest:
    return CommandRequest(
        workspace=_workspace(),
        action=CommandAction("quality.tests"),
        executable=ExecutableId("python"),
        arguments=("-m", "pytest"),
        working_directory=WorkingDirectory("src/project"),
        environment=(
            EnvironmentVariable("LANG", "C.UTF-8"),
            EnvironmentVariable("PYTHONHASHSEED", "0"),
        ),
        network_policy=NetworkPolicy.DENY_ALL,
        limits=_limits(),
    )


def _result(**changes: object) -> ExecutionResult:
    values: dict[str, object] = {
        "request": _request(),
        "termination": ExecutionTermination.EXITED,
        "exit_code": 0,
        "stdout": b"passed",
        "stderr": b"",
        "started_at": STARTED,
        "finished_at": FINISHED,
    }
    values.update(changes)
    return ExecutionResult(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["python", "python3.14", "uv-tool", "gate_driver"])
def test_executable_id_accepts_logical_non_path_identifiers(value: str) -> None:
    assert str(ExecutableId(value)) == value


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "Python", "/bin/python", "bin/python", "bin\\python", "a" * 65],
)
def test_executable_id_rejects_paths_and_ambiguous_values(value: str) -> None:
    with pytest.raises(ValueError):
        ExecutableId(value)


def test_executable_id_rejects_non_string_without_coercion() -> None:
    with pytest.raises(TypeError, match="executable_id must be a string"):
        ExecutableId(1)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["tests", "quality.tests", "build:wheel", "A_1"])
def test_command_action_accepts_bounded_policy_names(value: str) -> None:
    assert str(CommandAction(value)) == value


@pytest.mark.parametrize("value", ["", ".tests", "test action", "test/action", "a" * 129])
def test_command_action_rejects_invalid_names(value: str) -> None:
    with pytest.raises(ValueError):
        CommandAction(value)


def test_command_action_rejects_non_string_without_coercion() -> None:
    with pytest.raises(TypeError, match="command_action must be a string"):
        CommandAction(1)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [".", "src", "src/project", "a-b/c_d"])
def test_working_directory_accepts_normalized_relative_posix_paths(value: str) -> None:
    assert str(WorkingDirectory(value)) == value


@pytest.mark.parametrize(
    "value",
    ["", "/rooted", "../src", "src/../tests", "src/./tests", "src//tests", "src\\tests", "a\0b"],
)
def test_working_directory_rejects_escape_and_ambiguous_paths(value: str) -> None:
    with pytest.raises(ValueError):
        WorkingDirectory(value)


def test_working_directory_rejects_non_string_without_coercion() -> None:
    with pytest.raises(TypeError, match="working_directory must be a string"):
        WorkingDirectory(1)  # type: ignore[arg-type]


def test_environment_variable_accepts_explicit_name_and_value() -> None:
    assert EnvironmentVariable("PYTHONHASHSEED", "0") == EnvironmentVariable("PYTHONHASHSEED", "0")


@pytest.mark.parametrize("name", ["", "1NAME", "BAD-NAME", "BAD.NAME", "A" * 129 + "-"])
def test_environment_variable_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError):
        EnvironmentVariable(name, "value")


def test_environment_variable_rejects_non_string_name_and_value() -> None:
    with pytest.raises(TypeError, match="environment variable name must be a string"):
        EnvironmentVariable(1, "value")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="environment variable value must be a string"):
        EnvironmentVariable("NAME", 1)  # type: ignore[arg-type]


def test_environment_variable_rejects_nul_value() -> None:
    with pytest.raises(ValueError, match="cannot contain NUL"):
        EnvironmentVariable("NAME", "bad\0value")


def test_command_limits_accept_positive_integer_ceilings() -> None:
    assert _limits().timeout_ms == 30_000


@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize(
    "field",
    ["timeout_ms", "termination_grace_ms", "stdout_max_bytes", "stderr_max_bytes"],
)
def test_command_limits_reject_nonpositive_values(field: str, value: int) -> None:
    values = {
        "timeout_ms": 1,
        "termination_grace_ms": 1,
        "stdout_max_bytes": 1,
        "stderr_max_bytes": 1,
    }
    values[field] = value
    with pytest.raises(ValueError, match=f"{field} must be positive"):
        CommandLimits(**values)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_command_limits_reject_non_integer_values(value: object) -> None:
    with pytest.raises(TypeError, match="timeout_ms must be an integer"):
        CommandLimits(value, 1, 1, 1)  # type: ignore[arg-type]


def test_request_preserves_deterministic_provider_neutral_components() -> None:
    request = _request()
    assert request.arguments == ("-m", "pytest")
    assert tuple(entry.name for entry in request.environment) == (
        "LANG",
        "PYTHONHASHSEED",
    )
    assert request.network_policy is NetworkPolicy.DENY_ALL
    assert not hasattr(request, "path")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: replace(_request(), workspace=object()),
        lambda: replace(_request(), action=object()),
        lambda: replace(_request(), executable=object()),
        lambda: replace(_request(), arguments=["arg"]),
        lambda: replace(_request(), arguments=(1,)),
        lambda: replace(_request(), arguments=("bad\0arg",)),
        lambda: replace(_request(), working_directory=object()),
        lambda: replace(_request(), environment=[]),
        lambda: replace(_request(), environment=(object(),)),
        lambda: replace(
            _request(),
            environment=(EnvironmentVariable("Z", "1"), EnvironmentVariable("A", "2")),
        ),
        lambda: replace(
            _request(),
            environment=(EnvironmentVariable("A", "1"), EnvironmentVariable("A", "2")),
        ),
        lambda: replace(_request(), network_policy="deny_all"),
        lambda: replace(_request(), limits=object()),
    ],
)
def test_request_rejects_type_confusion_and_nondeterminism(
    factory: Callable[[], object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_exited_result_binds_request_outputs_and_utc_interval() -> None:
    result = _result()
    assert result.request == _request()
    assert result.termination is ExecutionTermination.EXITED
    assert result.exit_code == 0
    assert result.stdout == b"passed"
    assert result.finished_at > result.started_at


@pytest.mark.parametrize(
    "termination",
    [
        ExecutionTermination.TIMED_OUT,
        ExecutionTermination.CANCELLED,
        ExecutionTermination.OUTPUT_LIMIT,
    ],
)
def test_nonexit_terminations_require_absent_exit_code(
    termination: ExecutionTermination,
) -> None:
    result = _result(termination=termination, exit_code=None)
    assert result.exit_code is None


@pytest.mark.parametrize("exit_code", [None, True, "0"])
def test_exited_result_requires_integer_exit_code(exit_code: object) -> None:
    with pytest.raises(TypeError, match="exit_code must be an integer"):
        _result(exit_code=exit_code)


def test_nonexit_result_rejects_exit_code() -> None:
    with pytest.raises(ValueError, match="exit_code must be None"):
        _result(termination=ExecutionTermination.TIMED_OUT, exit_code=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request", object()),
        ("termination", "exited"),
        ("stdout", bytearray(b"output")),
        ("stderr", "error"),
        ("started_at", object()),
        ("finished_at", object()),
    ],
)
def test_result_rejects_semantic_type_confusion(field: str, value: object) -> None:
    with pytest.raises(TypeError):
        _result(**{field: value})


def test_result_rejects_outputs_above_request_ceilings() -> None:
    with pytest.raises(ValueError, match="stdout exceeds"):
        _result(stdout=b"x" * 17)
    with pytest.raises(ValueError, match="stderr exceeds"):
        _result(stderr=b"x" * 17)


def test_result_rejects_non_utc_or_reversed_intervals() -> None:
    with pytest.raises(ValueError, match="must use UTC"):
        _result(started_at=STARTED.replace(tzinfo=None))
    with pytest.raises(ValueError, match="must use UTC"):
        _result(finished_at=FINISHED.astimezone(timezone(timedelta(hours=1))))
    with pytest.raises(ValueError, match="cannot precede"):
        _result(started_at=FINISHED, finished_at=STARTED)


def test_command_values_are_frozen_slotted_and_semantically_distinct() -> None:
    request = _request()
    result = _result()
    values = (
        request.executable,
        request.action,
        request.working_directory,
        request.environment[0],
        request.limits,
        request,
        result,
    )
    assert all(not hasattr(value, "__dict__") for value in values)
    assert ExecutableId("tests") != CommandAction("tests")
    with pytest.raises(FrozenInstanceError):
        request.arguments = ()  # type: ignore[misc]
