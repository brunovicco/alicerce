"""Deterministic serialization and SHA-256 hashing for canonical evidence values."""

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Final, cast

import loop_schemas.models as canonical  # pyright: ignore[reportMissingTypeStubs]

from alicerce.domain.command import (
    CommandRequest,
    ExecutionResult,
    ExecutionTermination,
)

_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z")
_OBJECT_ID_PATTERN: Final = re.compile(r"[0-9a-f]{7,40}\Z")
_VERSION_PATTERN: Final = re.compile(r"\d+\.\d+\.\d+\Z")
_TERMINATIONS: Final = frozenset({"EXITED", "TIMED_OUT", "CANCELLED", "OUTPUT_LIMIT"})
_CANONICAL_TERMINATION: Final[dict[ExecutionTermination, canonical.ExecutionTermination]] = {
    ExecutionTermination.EXITED: "EXITED",
    ExecutionTermination.TIMED_OUT: "TIMED_OUT",
    ExecutionTermination.CANCELLED: "CANCELLED",
    ExecutionTermination.OUTPUT_LIMIT: "OUTPUT_LIMIT",
}


class EvidenceSerializationError(ValueError):
    """Raised when a canonical evidence value cannot be serialized safely."""


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise EvidenceSerializationError(f"{name} must be {expected.__name__}")
    return value


def _require_argument[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _text(value: object, *, name: str, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise EvidenceSerializationError(f"{name} must be a string")
    if nonempty and not value:
        raise EvidenceSerializationError(f"{name} must be non-empty")
    return value


def _matching_text(value: object, *, name: str, pattern: re.Pattern[str]) -> str:
    text = _text(value, name=name)
    if pattern.fullmatch(text) is None:
        raise EvidenceSerializationError(f"{name} has an invalid format")
    return text


def _signed_integer(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise EvidenceSerializationError(f"{name} must be an integer")
    return value


def _integer(value: object, *, name: str, minimum: int = 0) -> int:
    typed = _signed_integer(value, name=name)
    if typed < minimum:
        raise EvidenceSerializationError(f"{name} must be at least {minimum}")
    return typed


def _number(value: object, *, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceSerializationError(f"{name} must be a number")
    if not math.isfinite(value) or value < 0:
        raise EvidenceSerializationError(f"{name} must be finite and non-negative")
    return value


def _sequence(value: object, *, name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise EvidenceSerializationError(f"{name} must be a tuple")
    return cast(tuple[object, ...], value)


def _timestamp(value: object, *, name: str) -> str:
    text = _text(value, name=name, nonempty=True)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceSerializationError(f"{name} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise EvidenceSerializationError(f"{name} must include a timezone")
    return text


def _dump(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise EvidenceSerializationError(
            "evidence cannot be represented as deterministic JSON"
        ) from error


def _command_identity(request: CommandRequest) -> str:
    argv = [request.executable.value, *request.arguments]
    return json.dumps(
        argv,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _environment_payload(environment: canonical.Environment) -> dict[str, object]:
    trusted = _require_instance(
        environment,
        name="environment",
        expected=canonical.Environment,
    )
    raw_versions = cast(object, trusted.tool_versions)
    if not isinstance(raw_versions, dict):
        raise EvidenceSerializationError("environment.tool_versions must be a dictionary")
    versions: dict[str, object] = {}
    for key, value in cast(dict[object, object], raw_versions).items():
        name = _text(key, name="tool version name", nonempty=True)
        versions[name] = _text(value, name=f"tool version {name}", nonempty=True)
    return {
        "python": _text(trusted.python, name="environment.python", nonempty=True),
        "tool_versions": versions,
        "uv_lock_sha256": _matching_text(
            trusted.uv_lock_sha256,
            name="environment.uv_lock_sha256",
            pattern=_SHA256_PATTERN,
        ),
    }


def _command_payload(result: canonical.CommandResult) -> dict[str, object]:
    trusted = _require_instance(
        result,
        name="command_result",
        expected=canonical.CommandResult,
    )
    termination = _text(trusted.termination, name="command_result.termination")
    if termination not in _TERMINATIONS:
        raise EvidenceSerializationError("command_result.termination is unknown")
    if termination == "EXITED":
        exit_code: int | None = _signed_integer(
            trusted.exit_code,
            name="command_result.exit_code",
        )
    else:
        if trusted.exit_code is not None:
            raise EvidenceSerializationError(
                "command_result.exit_code must be null for forced termination"
            )
        exit_code = None
    return {
        "command": _text(trusted.command, name="command_result.command", nonempty=True),
        "duration_s": _number(trusted.duration_s, name="command_result.duration_s"),
        "exit_code": exit_code,
        "specification_sha256": _matching_text(
            trusted.specification_sha256,
            name="command_result.specification_sha256",
            pattern=_SHA256_PATTERN,
        ),
        "stderr_sha256": _matching_text(
            trusted.stderr_sha256,
            name="command_result.stderr_sha256",
            pattern=_SHA256_PATTERN,
        ),
        "stdout_sha256": _matching_text(
            trusted.stdout_sha256,
            name="command_result.stdout_sha256",
            pattern=_SHA256_PATTERN,
        ),
        "termination": termination,
    }


def _usage_payload(usage: canonical.Usage) -> dict[str, object]:
    trusted = _require_instance(usage, name="usage", expected=canonical.Usage)
    tokens = _require_instance(
        trusted.tokens,
        name="usage.tokens",
        expected=canonical.TokenUsage,
    )
    payload: dict[str, object] = {
        "model": _text(trusted.model, name="usage.model", nonempty=True),
        "provider": _text(trusted.provider, name="usage.provider", nonempty=True),
        "tokens": {
            "input": _integer(tokens.input, name="usage.tokens.input"),
            "output": _integer(tokens.output, name="usage.tokens.output"),
        },
    }
    if trusted.estimated_cost_usd is not None:
        payload["estimated_cost_usd"] = _number(
            trusted.estimated_cost_usd,
            name="usage.estimated_cost_usd",
        )
    return payload


def _evidence_payload(evidence: canonical.Evidence) -> dict[str, object]:
    trusted = _require_instance(evidence, name="evidence", expected=canonical.Evidence)
    commands = _sequence(cast(object, trusted.commands), name="evidence.commands")
    if not commands:
        raise EvidenceSerializationError("evidence.commands must not be empty")
    changed_files = _sequence(
        cast(object, trusted.changed_files),
        name="evidence.changed_files",
    )
    return {
        "baseline_sha": _matching_text(
            trusted.baseline_sha,
            name="evidence.baseline_sha",
            pattern=_OBJECT_ID_PATTERN,
        ),
        "candidate_sha": _matching_text(
            trusted.candidate_sha,
            name="evidence.candidate_sha",
            pattern=_OBJECT_ID_PATTERN,
        ),
        "changed_files": [_text(value, name="evidence.changed_file") for value in changed_files],
        "commands": [
            _command_payload(
                _require_instance(
                    value,
                    name="evidence command",
                    expected=canonical.CommandResult,
                )
            )
            for value in commands
        ],
        "contract_id": _text(trusted.contract_id, name="evidence.contract_id", nonempty=True),
        "environment": _environment_payload(trusted.environment),
        "finished_at": _timestamp(trusted.finished_at, name="evidence.finished_at"),
        "run_id": _text(trusted.run_id, name="evidence.run_id", nonempty=True),
        "started_at": _timestamp(trusted.started_at, name="evidence.started_at"),
        "usage": _usage_payload(trusted.usage),
        "version": _matching_text(
            trusted.version,
            name="evidence.version",
            pattern=_VERSION_PATTERN,
        ),
    }


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact trusted bytes."""
    if type(data) is not bytes:
        raise TypeError("data must be bytes")
    return hashlib.sha256(data).hexdigest()


def build_command_result(
    execution: ExecutionResult,
    *,
    specification_bytes: bytes,
) -> canonical.CommandResult:
    """Map one trusted operational result into the canonical evidence model."""
    trusted = _require_argument(
        execution,
        name="execution",
        expected=ExecutionResult,
    )
    if type(specification_bytes) is not bytes:
        raise TypeError("specification_bytes must be bytes")
    if not specification_bytes:
        raise EvidenceSerializationError("specification_bytes must be non-empty")
    duration = trusted.finished_at - trusted.started_at
    duration_s = duration.days * 86_400 + duration.seconds + duration.microseconds / 1_000_000
    result = canonical.CommandResult(
        command=_command_identity(trusted.request),
        termination=_CANONICAL_TERMINATION[trusted.termination],
        exit_code=trusted.exit_code,
        stdout_sha256=sha256_bytes(trusted.stdout),
        stderr_sha256=sha256_bytes(trusted.stderr),
        specification_sha256=sha256_bytes(specification_bytes),
        duration_s=duration_s,
    )
    serialize_command_result(result)
    return result


def serialize_environment(environment: canonical.Environment) -> bytes:
    """Serialize a canonical evidence environment deterministically."""
    trusted = _require_argument(
        environment,
        name="environment",
        expected=canonical.Environment,
    )
    return _dump(_environment_payload(trusted))


def serialize_command_result(result: canonical.CommandResult) -> bytes:
    """Serialize one canonical command result deterministically."""
    trusted = _require_argument(
        result,
        name="command_result",
        expected=canonical.CommandResult,
    )
    return _dump(_command_payload(trusted))


def serialize_evidence(evidence: canonical.Evidence) -> bytes:
    """Serialize a complete canonical evidence value deterministically."""
    trusted = _require_argument(evidence, name="evidence", expected=canonical.Evidence)
    return _dump(_evidence_payload(trusted))


def hash_environment(environment: canonical.Environment) -> str:
    """Hash the exact environment subtree used by canonical evidence."""
    return sha256_bytes(serialize_environment(environment))


def hash_command_result(result: canonical.CommandResult) -> str:
    """Hash the exact command-result subtree used by canonical evidence."""
    return sha256_bytes(serialize_command_result(result))


def hash_evidence(evidence: canonical.Evidence) -> str:
    """Hash the exact deterministic bytes of a complete evidence document."""
    return sha256_bytes(serialize_evidence(evidence))
