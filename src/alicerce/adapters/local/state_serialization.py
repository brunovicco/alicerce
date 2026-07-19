"""Canonical JSON serialization for trusted local run state."""

import json
from datetime import UTC, datetime
from typing import Final, cast

from alicerce.domain.contracts import FinalState
from alicerce.domain.lifecycle import (
    LifecycleActor,
    LifecycleState,
    LifecycleTransition,
    RunLifecycle,
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
from alicerce.domain.state import RunCheckpoint

STATE_FORMAT_VERSION: Final = 1
_IDENTITY_FORMAT: Final = "alicerce.run_identity"
_CHECKPOINT_FORMAT: Final = "alicerce.run_checkpoint"
_TRANSITION_FORMAT: Final = "alicerce.lifecycle_transition"
_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"


class StateSerializationError(ValueError):
    """Raised when state bytes are invalid, unknown, or noncanonical."""


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StateSerializationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise StateSerializationError(f"nonstandard JSON constant: {value}")


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
        raise StateSerializationError("state cannot be represented as canonical JSON") from error


def _load(data: bytes) -> dict[str, object]:
    if type(data) is not bytes:
        raise TypeError("serialized state must be bytes")
    try:
        text = data.decode("utf-8")
        value = cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_duplicate_rejecting_object,
                parse_constant=_reject_json_constant,
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StateSerializationError("serialized state must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise StateSerializationError("serialized state root must be an object")
    typed = cast(dict[str, object], value)
    if _dump(typed) != data:
        raise StateSerializationError("serialized state must use canonical JSON encoding")
    return typed


def _object(value: object, *, name: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise StateSerializationError(f"{name} must be an object")
    typed = cast(dict[str, object], value)
    if set(typed) != keys:
        raise StateSerializationError(f"{name} has invalid fields")
    return typed


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise StateSerializationError(f"{name} must be a string")
    return value


def _optional_text(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name=name)


def _integer(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise StateSerializationError(f"{name} must be an integer")
    return value


def _header(value: dict[str, object], *, expected_format: str) -> None:
    if value["format"] != expected_format:
        raise StateSerializationError("serialized state has an unexpected format")
    if _integer(value["version"], name="version") != STATE_FORMAT_VERSION:
        raise StateSerializationError("serialized state has an unsupported version")


def _timestamp(value: datetime) -> str:
    if value.tzinfo is not UTC:
        raise ValueError("state timestamps must use UTC timezone")
    return value.strftime(_TIMESTAMP_FORMAT)


def _parse_timestamp(value: object, *, name: str) -> datetime:
    text = _text(value, name=name)
    try:
        parsed = datetime.strptime(text, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError as error:
        raise StateSerializationError(f"{name} must be a canonical UTC timestamp") from error
    if _timestamp(parsed) != text:
        raise StateSerializationError(f"{name} must be a canonical UTC timestamp")
    return parsed


def _identity_payload(identity: RunIdentity) -> dict[str, object]:
    trusted = _require_instance(identity, name="identity", expected=RunIdentity)
    return {
        "baseline_sha": trusted.baseline_sha.value,
        "contract_hash": trusted.contract_hash.value,
        "contract_id": trusted.contract_id.value,
        "contract_version": trusted.contract_version.value,
        "created_at": _timestamp(trusted.created_at),
        "format": _IDENTITY_FORMAT,
        "policy_hash": trusted.policy_hash.value,
        "run_id": trusted.run_id.value,
        "version": STATE_FORMAT_VERSION,
    }


def _identity_from_payload(value: object) -> RunIdentity:
    payload = _object(
        value,
        name="identity",
        keys={
            "baseline_sha",
            "contract_hash",
            "contract_id",
            "contract_version",
            "created_at",
            "format",
            "policy_hash",
            "run_id",
            "version",
        },
    )
    _header(payload, expected_format=_IDENTITY_FORMAT)
    try:
        return RunIdentity(
            run_id=RunId(_text(payload["run_id"], name="run_id")),
            contract_id=ContractId(_text(payload["contract_id"], name="contract_id")),
            contract_version=ContractVersion(
                _text(payload["contract_version"], name="contract_version")
            ),
            contract_hash=ContractHash(_text(payload["contract_hash"], name="contract_hash")),
            baseline_sha=BaselineSha(_text(payload["baseline_sha"], name="baseline_sha")),
            policy_hash=PolicyHash(_text(payload["policy_hash"], name="policy_hash")),
            created_at=_parse_timestamp(payload["created_at"], name="created_at"),
        )
    except (TypeError, ValueError) as error:
        raise StateSerializationError("identity contains invalid domain values") from error


def serialize_run_identity(identity: RunIdentity) -> bytes:
    """Serialize one immutable identity to canonical versioned JSON bytes."""
    return _dump(_identity_payload(identity))


def deserialize_run_identity(data: bytes) -> RunIdentity:
    """Reconstruct one identity only from canonical supported bytes."""
    return _identity_from_payload(_load(data))


def serialize_checkpoint(checkpoint: RunCheckpoint) -> bytes:
    """Serialize one complete checkpoint to canonical versioned JSON bytes."""
    trusted = _require_instance(checkpoint, name="checkpoint", expected=RunCheckpoint)
    lifecycle = trusted.lifecycle
    return _dump(
        {
            "final_state": lifecycle.final_state,
            "format": _CHECKPOINT_FORMAT,
            "identity": _identity_payload(trusted.identity),
            "revision": lifecycle.revision,
            "state": lifecycle.state.value,
            "updated_at": _timestamp(lifecycle.updated_at),
            "version": STATE_FORMAT_VERSION,
        }
    )


def deserialize_checkpoint(data: bytes) -> RunCheckpoint:
    """Reconstruct one checkpoint only from canonical supported bytes."""
    payload = _object(
        _load(data),
        name="checkpoint",
        keys={
            "final_state",
            "format",
            "identity",
            "revision",
            "state",
            "updated_at",
            "version",
        },
    )
    _header(payload, expected_format=_CHECKPOINT_FORMAT)
    try:
        identity = _identity_from_payload(payload["identity"])
        lifecycle = RunLifecycle(
            run_id=identity.run_id,
            state=LifecycleState(_text(payload["state"], name="state")),
            revision=_integer(payload["revision"], name="revision"),
            updated_at=_parse_timestamp(payload["updated_at"], name="updated_at"),
            final_state=cast(
                FinalState | None,
                _optional_text(payload["final_state"], name="final_state"),
            ),
        )
        return RunCheckpoint(identity=identity, lifecycle=lifecycle)
    except (TypeError, ValueError) as error:
        raise StateSerializationError("checkpoint contains invalid domain values") from error


def serialize_transition(transition: LifecycleTransition) -> bytes:
    """Serialize one attributed transition to canonical versioned JSON bytes."""
    trusted = _require_instance(
        transition,
        name="transition",
        expected=LifecycleTransition,
    )
    return _dump(
        {
            "actor": trusted.actor.value,
            "final_state": trusted.final_state,
            "format": _TRANSITION_FORMAT,
            "from_state": trusted.from_state.value,
            "occurred_at": _timestamp(trusted.occurred_at),
            "revision": trusted.revision,
            "run_id": trusted.run_id.value,
            "to_state": trusted.to_state.value,
            "version": STATE_FORMAT_VERSION,
        }
    )


def deserialize_transition(data: bytes) -> LifecycleTransition:
    """Reconstruct one transition only from canonical supported bytes."""
    payload = _object(
        _load(data),
        name="transition",
        keys={
            "actor",
            "final_state",
            "format",
            "from_state",
            "occurred_at",
            "revision",
            "run_id",
            "to_state",
            "version",
        },
    )
    _header(payload, expected_format=_TRANSITION_FORMAT)
    try:
        return LifecycleTransition(
            run_id=RunId(_text(payload["run_id"], name="run_id")),
            revision=_integer(payload["revision"], name="revision"),
            from_state=LifecycleState(_text(payload["from_state"], name="from_state")),
            to_state=LifecycleState(_text(payload["to_state"], name="to_state")),
            occurred_at=_parse_timestamp(payload["occurred_at"], name="occurred_at"),
            actor=LifecycleActor(_text(payload["actor"], name="actor")),
            final_state=cast(
                FinalState | None,
                _optional_text(payload["final_state"], name="final_state"),
            ),
        )
    except (TypeError, ValueError) as error:
        raise StateSerializationError("transition contains invalid domain values") from error
