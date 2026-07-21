"""Tests for trusted operational-result to canonical command-result mapping."""

from datetime import UTC, datetime, timedelta
from typing import cast

import loop_schemas.models as canonical  # pyright: ignore[reportMissingTypeStubs]
import pytest

from alicerce.adapters.local.evidence_serialization import (
    EvidenceSerializationError,
    build_command_result,
    serialize_command_result,
    sha256_bytes,
)
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

STARTED = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
SPECIFICATION = b'{"driver":"pytest","version":1}'


def _request(
    *, arguments: tuple[str, ...] = ("-m", "pytest", "tests/unit test.py")
) -> CommandRequest:
    run_identity = RunIdentity(
        run_id=RunId("run-evidence"),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("1.0.0"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        created_at=STARTED,
    )
    workspace = WorkspaceIdentity(
        workspace_id=WorkspaceId("workspace-evidence"),
        run_id=run_identity.run_id,
        baseline_sha=run_identity.baseline_sha,
    )
    return CommandRequest(
        run_identity=run_identity,
        workspace=workspace,
        action=CommandAction("test"),
        executable=ExecutableId("python"),
        arguments=arguments,
        working_directory=WorkingDirectory("."),
        environment=(EnvironmentVariable("LC_ALL", "C.UTF-8"),),
        network_policy=NetworkPolicy.DENY_ALL,
        limits=CommandLimits(
            timeout_ms=10_000,
            termination_grace_ms=500,
            stdout_max_bytes=4_096,
            stderr_max_bytes=4_096,
        ),
    )


def _execution(
    *,
    termination: ExecutionTermination = ExecutionTermination.EXITED,
    exit_code: int | None = 0,
    stdout: bytes = b"passed\n",
    stderr: bytes = b"",
    duration: timedelta = timedelta(seconds=1, microseconds=250_000),
    arguments: tuple[str, ...] = ("-m", "pytest", "tests/unit test.py"),
) -> ExecutionResult:
    return ExecutionResult(
        request=_request(arguments=arguments),
        termination=termination,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        started_at=STARTED,
        finished_at=STARTED + duration,
    )


def test_build_command_result_maps_every_integrity_field_without_a_shell() -> None:
    execution = _execution(stderr=b"warning\n")

    result = build_command_result(
        execution,
        specification_bytes=SPECIFICATION,
    )

    assert type(result) is canonical.CommandResult
    assert result == canonical.CommandResult(
        command='["python","-m","pytest","tests/unit test.py"]',
        termination="EXITED",
        exit_code=0,
        stdout_sha256=sha256_bytes(b"passed\n"),
        stderr_sha256=sha256_bytes(b"warning\n"),
        specification_sha256=sha256_bytes(SPECIFICATION),
        duration_s=1.25,
    )
    assert serialize_command_result(result)
    assert "shell" not in result.command


@pytest.mark.parametrize(
    ("termination", "exit_code", "canonical_termination"),
    [
        (ExecutionTermination.EXITED, 7, "EXITED"),
        (ExecutionTermination.TIMED_OUT, None, "TIMED_OUT"),
        (ExecutionTermination.CANCELLED, None, "CANCELLED"),
        (ExecutionTermination.OUTPUT_LIMIT, None, "OUTPUT_LIMIT"),
    ],
)
def test_build_command_result_maps_all_typed_terminations(
    termination: ExecutionTermination,
    exit_code: int | None,
    canonical_termination: canonical.ExecutionTermination,
) -> None:
    result = build_command_result(
        _execution(termination=termination, exit_code=exit_code),
        specification_bytes=SPECIFICATION,
    )

    assert result.termination == canonical_termination
    assert result.exit_code == exit_code


def test_command_identity_is_unambiguous_for_spaces_quotes_and_shell_tokens() -> None:
    result = build_command_result(
        _execution(arguments=("two words", 'a"b', ";", "${HOME}")),
        specification_bytes=SPECIFICATION,
    )

    assert result.command == '["python","two words","a\\"b",";","${HOME}"]'


def test_hashes_bind_exact_output_and_specification_bytes() -> None:
    original = build_command_result(
        _execution(),
        specification_bytes=SPECIFICATION,
    )
    changed_stdout = build_command_result(
        _execution(stdout=b"passed\r\n"),
        specification_bytes=SPECIFICATION,
    )
    changed_stderr = build_command_result(
        _execution(stderr=b" "),
        specification_bytes=SPECIFICATION,
    )
    changed_specification = build_command_result(
        _execution(),
        specification_bytes=SPECIFICATION + b"\n",
    )

    assert changed_stdout.stdout_sha256 != original.stdout_sha256
    assert changed_stderr.stderr_sha256 != original.stderr_sha256
    assert changed_specification.specification_sha256 != original.specification_sha256


def test_duration_uses_the_complete_trusted_execution_interval() -> None:
    result = build_command_result(
        _execution(duration=timedelta(days=1, seconds=2, microseconds=3)),
        specification_bytes=SPECIFICATION,
    )

    assert result.duration_s == 86_402.000003


def test_builder_rejects_missing_or_mistyped_inputs() -> None:
    with pytest.raises(TypeError):
        build_command_result(
            cast(ExecutionResult, object()),
            specification_bytes=SPECIFICATION,
        )
    with pytest.raises(TypeError):
        build_command_result(
            _execution(),
            specification_bytes=cast(bytes, bytearray(SPECIFICATION)),
        )
    with pytest.raises(EvidenceSerializationError):
        build_command_result(_execution(), specification_bytes=b"")


def test_builder_rejects_command_identity_that_cannot_be_utf8_serialized() -> None:
    execution = _execution(arguments=("\ud800",))

    with pytest.raises(EvidenceSerializationError):
        build_command_result(
            execution,
            specification_bytes=SPECIFICATION,
        )
