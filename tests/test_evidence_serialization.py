"""Tests for deterministic canonical evidence serialization and hashing."""

import json
from dataclasses import replace
from typing import cast

import loop_schemas.models as canonical  # pyright: ignore[reportMissingTypeStubs]
import pytest

from alicerce.adapters.local.evidence_serialization import (
    EvidenceSerializationError,
    hash_command_result,
    hash_environment,
    hash_evidence,
    serialize_command_result,
    serialize_environment,
    serialize_evidence,
    sha256_bytes,
)


def _environment() -> canonical.Environment:
    return canonical.Environment(
        python="3.12.13",
        uv_lock_sha256="a" * 64,
        tool_versions={"pytest": "9.1.1", "ruff": "0.15.21"},
    )


def _command(
    *,
    termination: canonical.ExecutionTermination = "EXITED",
    exit_code: int | None = 0,
) -> canonical.CommandResult:
    return canonical.CommandResult(
        command="uv run pytest",
        termination=termination,
        exit_code=exit_code,
        stdout_sha256="b" * 64,
        stderr_sha256="c" * 64,
        specification_sha256="d" * 64,
        duration_s=1.25,
    )


def _usage(*, estimated_cost_usd: float | None = None) -> canonical.Usage:
    return canonical.Usage(
        provider="local",
        model="deterministic",
        tokens=canonical.TokenUsage(input=0, output=0),
        estimated_cost_usd=estimated_cost_usd,
    )


def _evidence() -> canonical.Evidence:
    return canonical.Evidence(
        version="1.0.0",
        run_id="run-001",
        contract_id="quality-loop",
        baseline_sha="e" * 40,
        candidate_sha="f" * 40,
        environment=_environment(),
        commands=(_command(),),
        changed_files=("src/example.py", "tests/test_example.py"),
        usage=_usage(),
        started_at="2026-07-21T12:00:00Z",
        finished_at="2026-07-21T12:00:02Z",
    )


def _decoded(data: bytes) -> dict[str, object]:
    value = json.loads(data)
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_exact_byte_hash_uses_the_standard_lowercase_sha256_vector() -> None:
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    with pytest.raises(TypeError):
        sha256_bytes(cast(bytes, bytearray(b"abc")))


def test_environment_serialization_is_compact_sorted_utf8_and_order_independent() -> None:
    environment = _environment()
    reordered = replace(
        environment,
        tool_versions={"ruff": "0.15.21", "pytest": "9.1.1"},
    )

    serialized = serialize_environment(environment)

    assert serialized == serialize_environment(reordered)
    assert serialized == (
        b'{"python":"3.12.13","tool_versions":{"pytest":"9.1.1",'
        b'"ruff":"0.15.21"},"uv_lock_sha256":"' + b"a" * 64 + b'"}'
    )
    assert hash_environment(environment) == sha256_bytes(serialized)


def test_command_serialization_preserves_null_exit_code_and_every_integrity_hash() -> None:
    timed_out = _command(termination="TIMED_OUT", exit_code=None)

    serialized = serialize_command_result(timed_out)
    payload = _decoded(serialized)

    assert payload == {
        "command": "uv run pytest",
        "duration_s": 1.25,
        "exit_code": None,
        "specification_sha256": "d" * 64,
        "stderr_sha256": "c" * 64,
        "stdout_sha256": "b" * 64,
        "termination": "TIMED_OUT",
    }
    assert hash_command_result(timed_out) == sha256_bytes(serialized)

    large_negative_exit = replace(_command(), exit_code=-(2**100))
    assert _decoded(serialize_command_result(large_negative_exit))["exit_code"] == -(2**100)


def test_evidence_serialization_matches_its_canonical_subtrees_and_omits_absent_cost() -> None:
    evidence = _evidence()

    serialized = serialize_evidence(evidence)
    payload = _decoded(serialized)

    assert payload["environment"] == _decoded(serialize_environment(evidence.environment))
    commands = payload["commands"]
    assert isinstance(commands, list)
    assert commands == [_decoded(serialize_command_result(evidence.commands[0]))]
    assert payload["usage"] == {
        "model": "deterministic",
        "provider": "local",
        "tokens": {"input": 0, "output": 0},
    }
    assert b'": "' not in serialized
    assert b'", "' not in serialized
    assert hash_evidence(evidence) == sha256_bytes(serialized)

    with_cost = replace(evidence, usage=_usage(estimated_cost_usd=0.125))
    assert _decoded(serialize_evidence(with_cost))["usage"] == {
        "estimated_cost_usd": 0.125,
        "model": "deterministic",
        "provider": "local",
        "tokens": {"input": 0, "output": 0},
    }


def test_every_a08_binding_changes_the_final_evidence_hash() -> None:
    evidence = _evidence()
    original = hash_evidence(evidence)
    command = evidence.commands[0]

    variants = (
        replace(evidence, candidate_sha="0" * 40),
        replace(evidence, environment=replace(evidence.environment, python="3.13.12")),
        replace(
            evidence,
            commands=(replace(command, stdout_sha256="1" * 64),),
        ),
        replace(
            evidence,
            commands=(replace(command, stderr_sha256="2" * 64),),
        ),
        replace(
            evidence,
            commands=(replace(command, specification_sha256="3" * 64),),
        ),
    )

    assert all(hash_evidence(variant) != original for variant in variants)
    assert len({hash_evidence(variant) for variant in variants}) == len(variants)


@pytest.mark.parametrize(
    "result",
    [
        replace(_command(), command=""),
        replace(
            _command(),
            termination=cast(canonical.ExecutionTermination, "UNKNOWN"),
        ),
        replace(_command(), exit_code=None),
        _command(termination="TIMED_OUT", exit_code=1),
        replace(_command(), exit_code=cast(int, True)),
        replace(_command(), duration_s=cast(float, True)),
        replace(_command(), duration_s=-1.0),
        replace(_command(), duration_s=float("nan")),
        replace(_command(), stdout_sha256="A" * 64),
        replace(_command(), stderr_sha256="short"),
        replace(_command(), specification_sha256=""),
    ],
)
def test_command_serialization_rejects_invalid_or_contradictory_values(
    result: canonical.CommandResult,
) -> None:
    with pytest.raises(EvidenceSerializationError):
        serialize_command_result(result)


@pytest.mark.parametrize(
    "environment",
    [
        replace(_environment(), python=""),
        replace(_environment(), uv_lock_sha256="A" * 64),
        replace(
            _environment(),
            tool_versions=cast(dict[str, str], [("ruff", "0.15.21")]),
        ),
        replace(
            _environment(),
            tool_versions=cast(dict[str, str], {1: "0.15.21"}),
        ),
        replace(_environment(), tool_versions={"ruff": ""}),
    ],
)
def test_environment_serialization_rejects_invalid_values(
    environment: canonical.Environment,
) -> None:
    with pytest.raises(EvidenceSerializationError):
        serialize_environment(environment)


@pytest.mark.parametrize(
    "evidence",
    [
        replace(_evidence(), version="v1"),
        replace(_evidence(), run_id=""),
        replace(_evidence(), contract_id=""),
        replace(_evidence(), baseline_sha="A" * 40),
        replace(_evidence(), candidate_sha="short"),
        replace(_evidence(), commands=()),
        replace(_evidence(), commands=cast(tuple[canonical.CommandResult, ...], [])),
        replace(
            _evidence(),
            commands=cast(tuple[canonical.CommandResult, ...], ("not-a-command",)),
        ),
        replace(_evidence(), changed_files=cast(tuple[str, ...], [])),
        replace(_evidence(), changed_files=(cast(str, 7),)),
        replace(_evidence(), started_at="not-a-time"),
        replace(_evidence(), finished_at="2026-07-21T12:00:02"),
        replace(_evidence(), changed_files=("\ud800",)),
        replace(_evidence(), usage=replace(_usage(), provider="")),
        replace(_evidence(), usage=replace(_usage(), model="")),
        replace(
            _evidence(),
            usage=replace(
                _usage(),
                tokens=canonical.TokenUsage(input=cast(int, True), output=0),
            ),
        ),
        replace(
            _evidence(),
            usage=replace(
                _usage(),
                tokens=canonical.TokenUsage(input=-1, output=0),
            ),
        ),
        replace(
            _evidence(),
            usage=replace(_usage(), estimated_cost_usd=float("inf")),
        ),
    ],
)
def test_evidence_serialization_rejects_invalid_canonical_values(
    evidence: canonical.Evidence,
) -> None:
    with pytest.raises(EvidenceSerializationError):
        serialize_evidence(evidence)


def test_serializers_reject_noncanonical_top_level_types() -> None:
    with pytest.raises(TypeError):
        serialize_environment(cast(canonical.Environment, object()))
    with pytest.raises(TypeError):
        serialize_command_result(cast(canonical.CommandResult, object()))
    with pytest.raises(TypeError):
        serialize_evidence(cast(canonical.Evidence, object()))
