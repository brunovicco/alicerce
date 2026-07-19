"""Tests for immutable run identity values."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)

SHA256_A = "a" * 64
SHA256_B = "b" * 64
BASELINE_SHA1 = "c" * 40
CREATED_AT = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _identity(**changes: Any) -> RunIdentity:
    values: dict[str, Any] = {
        "run_id": RunId("run-001"),
        "contract_id": ContractId("quality-loop"),
        "contract_version": ContractVersion("0.1.2"),
        "contract_hash": ContractHash(SHA256_A),
        "baseline_sha": BaselineSha(BASELINE_SHA1),
        "policy_hash": PolicyHash(SHA256_B),
        "created_at": CREATED_AT,
    }
    values.update(changes)
    return RunIdentity(**values)


def test_run_identity_accepts_complete_baseline_object_ids() -> None:
    """Both supported full object identifier lengths are accepted."""
    assert _identity().baseline_sha == BaselineSha(BASELINE_SHA1)
    assert _identity(baseline_sha=BaselineSha("d" * 64)).baseline_sha.value == "d" * 64


@pytest.mark.parametrize(
    "value",
    ["", " run-001", "run 001", ".run", "../run", "run/001", "éxecution", "r" * 129],
)
def test_run_id_rejects_unsafe_or_noncanonical_values(value: str) -> None:
    """Run identifiers remain safe for later use as directory names."""
    with pytest.raises(ValueError):
        RunId(value)


@pytest.mark.parametrize("factory", [RunId, ContractId, ContractVersion])
def test_text_values_reject_non_strings(factory: Any) -> None:
    """String-backed values reject runtime type confusion."""
    with pytest.raises(TypeError):
        factory(123)


@pytest.mark.parametrize("factory", [ContractId, ContractVersion])
@pytest.mark.parametrize("value", ["", " value", "value "])
def test_contract_metadata_wrappers_reject_invalid_text(factory: Any, value: str) -> None:
    """Canonical metadata wrappers reject empty or padded values."""
    with pytest.raises(ValueError):
        factory(value)


@pytest.mark.parametrize("factory", [ContractHash, PolicyHash])
@pytest.mark.parametrize(
    "value",
    ["", "a" * 39, "a" * 40, "a" * 63, "a" * 65, "A" * 64, "g" * 64, " a" * 32],
)
def test_sha256_values_reject_invalid_digests(factory: Any, value: str) -> None:
    """Trusted bindings require complete lowercase SHA-256 digests."""
    with pytest.raises(ValueError):
        factory(value)


@pytest.mark.parametrize("value", ["", "a" * 7, "a" * 39, "a" * 41, "A" * 40, "g" * 40])
def test_baseline_sha_rejects_abbreviated_or_invalid_values(value: str) -> None:
    """Baseline identity never accepts abbreviated or noncanonical digests."""
    with pytest.raises(ValueError):
        BaselineSha(value)


def test_values_and_identity_are_frozen_and_slotted() -> None:
    """Bindings cannot be mutated and expose no instance dictionary."""
    run_id = RunId("run-001")
    identity = _identity()

    with pytest.raises(FrozenInstanceError):
        run_id.value = "run-002"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        identity.run_id = RunId("run-002")  # type: ignore[misc]

    assert not hasattr(run_id, "__dict__")
    assert not hasattr(identity, "__dict__")


def test_semantic_values_are_equal_and_hashable_only_within_their_type() -> None:
    """Equal text cannot collapse distinct identity concepts."""
    contract_hash = ContractHash(SHA256_A)
    assert contract_hash == ContractHash(SHA256_A)
    assert hash(contract_hash) == hash(ContractHash(SHA256_A))
    assert contract_hash != PolicyHash(SHA256_A)
    assert contract_hash != SHA256_A


@pytest.mark.parametrize(
    ("wrapped", "expected"),
    [
        (RunId("run-001"), "run-001"),
        (ContractId("quality-loop"), "quality-loop"),
        (ContractVersion("0.1.2"), "0.1.2"),
        (ContractHash(SHA256_A), SHA256_A),
        (BaselineSha(BASELINE_SHA1), BASELINE_SHA1),
        (PolicyHash(SHA256_B), SHA256_B),
    ],
)
def test_semantic_values_have_explicit_string_projection(wrapped: object, expected: str) -> None:
    """Serialization callers can explicitly project a wrapper to its text."""
    assert str(wrapped) == expected


def test_run_identity_equality_covers_every_binding() -> None:
    """Any changed trusted binding produces a different identity."""
    original = _identity()
    assert original == _identity()
    assert hash(original) == hash(_identity())

    alternatives = (
        _identity(run_id=RunId("run-002")),
        _identity(contract_id=ContractId("other-loop")),
        _identity(contract_version=ContractVersion("0.1.3")),
        _identity(contract_hash=ContractHash("e" * 64)),
        _identity(baseline_sha=BaselineSha("f" * 40)),
        _identity(policy_hash=PolicyHash("0" * 64)),
        _identity(created_at=CREATED_AT + timedelta(seconds=1)),
    )
    assert all(candidate != original for candidate in alternatives)


def test_run_identity_rejects_transposed_semantic_types_at_runtime() -> None:
    """Direct construction cannot transpose adjacent string-backed fields."""
    with pytest.raises(TypeError, match="contract_id must be ContractId"):
        _identity(contract_id=ContractVersion("quality-loop"))


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 7, 19, 12, 0),
        datetime(2026, 7, 19, 12, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_run_identity_rejects_naive_or_non_utc_time(created_at: datetime) -> None:
    """Identity timestamps must be explicit UTC values."""
    with pytest.raises(ValueError, match="UTC"):
        _identity(created_at=created_at)


def test_run_identity_rejects_non_datetime_time() -> None:
    """Runtime construction rejects incorrectly typed timestamps."""
    with pytest.raises(TypeError, match="datetime"):
        _identity(created_at="2026-07-19T12:00:00Z")
