"""Tests for canonical local run-state serialization."""

import json
from datetime import UTC, datetime

import pytest

from alicerce.adapters.local import state_serialization as codec
from alicerce.adapters.local.state_serialization import (
    STATE_FORMAT_VERSION,
    StateSerializationError,
    deserialize_checkpoint,
    deserialize_run_identity,
    deserialize_transition,
    serialize_checkpoint,
    serialize_run_identity,
    serialize_transition,
)
from alicerce.domain.lifecycle import LifecycleActor, LifecycleState, LifecycleTransition
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)
from alicerce.domain.state import create_initial_checkpoint, prepare_state_update

NOW = datetime(2026, 7, 19, 22, 0, tzinfo=UTC)


def _identity() -> RunIdentity:
    return RunIdentity(
        run_id=RunId("run-sqlite"),
        contract_id=ContractId("quality-loop"),
        contract_version=ContractVersion("0.1.2"),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        created_at=NOW,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _decoded(data: bytes) -> dict[str, object]:
    value = json.loads(data)
    assert isinstance(value, dict)
    return value


def _transition() -> LifecycleTransition:
    checkpoint = create_initial_checkpoint(_identity())
    return prepare_state_update(
        checkpoint,
        to_state=LifecycleState.WORKSPACE_PREPARED,
        occurred_at=NOW,
        actor=LifecycleActor("test.codec"),
    ).advance.transition


def test_identity_checkpoint_and_transition_round_trip_exactly() -> None:
    identity = _identity()
    checkpoint = create_initial_checkpoint(identity)
    transition = _transition()

    identity_bytes = serialize_run_identity(identity)
    checkpoint_bytes = serialize_checkpoint(checkpoint)
    transition_bytes = serialize_transition(transition)

    assert deserialize_run_identity(identity_bytes) == identity
    assert deserialize_checkpoint(checkpoint_bytes) == checkpoint
    assert deserialize_transition(transition_bytes) == transition
    assert serialize_run_identity(deserialize_run_identity(identity_bytes)) == identity_bytes
    assert serialize_checkpoint(deserialize_checkpoint(checkpoint_bytes)) == checkpoint_bytes
    assert serialize_transition(deserialize_transition(transition_bytes)) == transition_bytes
    assert b" " not in identity_bytes
    assert _decoded(identity_bytes)["version"] == STATE_FORMAT_VERSION


def test_terminal_checkpoint_and_transition_preserve_canonical_final_state() -> None:
    checkpoint = create_initial_checkpoint(_identity())
    update = prepare_state_update(
        checkpoint,
        to_state=LifecycleState.COMPLETED,
        occurred_at=NOW,
        actor=LifecycleActor("test.codec"),
        final_state="INFRA_FAILED",
    )
    terminal = update.next_checkpoint
    assert deserialize_checkpoint(serialize_checkpoint(terminal)) == terminal
    assert deserialize_transition(serialize_transition(update.advance.transition)) == (
        update.advance.transition
    )


@pytest.mark.parametrize(
    "data",
    [
        b"\xff",
        b"not-json",
        b"[]",
        b'{"format":"x","format":"x"}',
        b'{ "format": "x" }',
        b'{"value":NaN}',
        b'{"value":"\\ud800"}',
    ],
)
def test_decoder_rejects_invalid_duplicate_root_and_noncanonical_json(data: bytes) -> None:
    with pytest.raises(StateSerializationError):
        deserialize_run_identity(data)


def test_identity_decoder_rejects_fields_header_types_and_domain_values() -> None:
    valid = _decoded(serialize_run_identity(_identity()))
    cases: list[dict[str, object]] = []

    missing = dict(valid)
    missing.pop("policy_hash")
    cases.append(missing)
    extra = {**valid, "extra": True}
    cases.append(extra)
    cases.append({**valid, "format": "unknown"})
    cases.append({**valid, "version": 2})
    cases.append({**valid, "version": True})
    cases.append({**valid, "run_id": 7})
    cases.append({**valid, "run_id": ".unsafe"})
    cases.append({**valid, "created_at": "2026-07-19T22:00:00Z"})
    cases.append({**valid, "created_at": "not-a-time"})
    cases.append({**valid, "created_at": "2026-07-19T22:00:00.0Z"})

    for payload in cases:
        with pytest.raises(StateSerializationError):
            deserialize_run_identity(_canonical(payload))


def test_checkpoint_decoder_rejects_invalid_nested_and_lifecycle_values() -> None:
    valid = _decoded(serialize_checkpoint(create_initial_checkpoint(_identity())))
    cases: list[dict[str, object]] = [
        {**valid, "identity": "not-an-object"},
        {**valid, "state": "unknown"},
        {**valid, "revision": True},
        {**valid, "final_state": 1},
        {**valid, "final_state": "SUCCEEDED"},
        {**valid, "updated_at": "2026-07-19T22:00:00.000000+00:00"},
    ]
    missing = dict(valid)
    missing.pop("state")
    cases.append(missing)

    for payload in cases:
        with pytest.raises(StateSerializationError):
            deserialize_checkpoint(_canonical(payload))


def test_transition_decoder_rejects_invalid_fields_and_domain_values() -> None:
    valid = _decoded(serialize_transition(_transition()))
    cases: list[dict[str, object]] = [
        {**valid, "actor": "Unsafe Actor"},
        {**valid, "from_state": "unknown"},
        {**valid, "to_state": 2},
        {**valid, "revision": "1"},
        {**valid, "run_id": ".."},
        {**valid, "final_state": "SUCCEEDED"},
    ]
    extra = {**valid, "extra": None}
    cases.append(extra)

    for payload in cases:
        with pytest.raises(StateSerializationError):
            deserialize_transition(_canonical(payload))


def test_serializers_reject_wrong_types_and_non_utc_internal_timestamp() -> None:
    with pytest.raises(TypeError, match="identity must be RunIdentity"):
        serialize_run_identity(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="checkpoint must be RunCheckpoint"):
        serialize_checkpoint(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="transition must be LifecycleTransition"):
        serialize_transition(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="serialized state must be bytes"):
        deserialize_run_identity("{}")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="UTC"):
        codec._timestamp(  # pyright: ignore[reportPrivateUsage]
            datetime(2026, 7, 19)
        )


def test_serialization_error_is_a_value_error() -> None:
    assert isinstance(StateSerializationError("invalid"), ValueError)
