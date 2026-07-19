"""Tests for exact-byte canonical contract binding."""

import hashlib
from dataclasses import FrozenInstanceError

import pytest

import alicerce.domain.contract_binding as binding_module
from alicerce.application.contract_binding import bind_contract
from alicerce.domain.contract_binding import (
    BoundContract,
    ContractBindingCause,
    ContractBindingError,
)
from alicerce.domain.contracts import Contract
from alicerce.domain.run_identity import ContractHash

CONTRACT_BYTES = b"""{
  "version": "0.1.2",
  "id": "quality-loop",
  "objective": "Improve repository quality.",
  "trigger": {"type": "manual"},
  "selection": {"strategy": "single-item"},
  "baseline": {"commands": ["quality"]},
  "acceptance": {"hard_gates": ["tests"]},
  "budgets": {"max_tokens": 10},
  "scope": {"allowlist": ["src/**"], "denylist": []},
  "actions": {"allowed": ["edit"], "denied": []},
  "human_review": {"required": true}
}"""


def test_binding_uses_exact_bytes_and_canonical_contract() -> None:
    """One binding derives its model and digest from the same immutable bytes."""
    binding = bind_contract(CONTRACT_BYTES)
    assert type(binding.contract) is Contract
    assert binding.source_bytes is CONTRACT_BYTES
    assert binding.contract_hash == ContractHash(hashlib.sha256(CONTRACT_BYTES).hexdigest())
    assert binding == bind_contract(CONTRACT_BYTES)


@pytest.mark.parametrize(
    "changed",
    [CONTRACT_BYTES + b"\n", CONTRACT_BYTES.replace(b'  "id"', b'   "id"', 1)],
)
def test_any_byte_change_produces_a_different_identity(changed: bytes) -> None:
    """Whitespace and newline changes identify a different reviewed artifact."""
    assert bind_contract(changed).contract == bind_contract(CONTRACT_BYTES).contract
    assert bind_contract(changed).contract_hash != bind_contract(CONTRACT_BYTES).contract_hash


def test_content_change_updates_contract_and_hash() -> None:
    """A semantic mutation changes both the canonical model and source digest."""
    changed = CONTRACT_BYTES.replace(b"quality-loop", b"other-loop")
    original = bind_contract(CONTRACT_BYTES)
    mutated = bind_contract(changed)
    assert mutated.contract.id == "other-loop"
    assert mutated.contract != original.contract
    assert mutated.contract_hash != original.contract_hash


def test_bound_contract_is_frozen_and_slotted() -> None:
    """Source identity cannot be mutated after validation."""
    binding = bind_contract(CONTRACT_BYTES)
    with pytest.raises(FrozenInstanceError):
        binding.source_bytes = b"{}"  # type: ignore[misc]
    assert not hasattr(binding, "__dict__")


def test_direct_construction_rejects_unrelated_hash() -> None:
    """Even direct construction revalidates source correspondence."""
    trusted = bind_contract(CONTRACT_BYTES)
    with pytest.raises(ContractBindingError) as captured:
        BoundContract(
            contract=trusted.contract,
            contract_hash=ContractHash("f" * 64),
            source_bytes=CONTRACT_BYTES,
        )
    assert captured.value.cause is ContractBindingCause.BINDING_MISMATCH


def test_direct_construction_rejects_unrelated_contract() -> None:
    """A contract parsed from other bytes cannot reuse the original source hash."""
    original = bind_contract(CONTRACT_BYTES)
    changed = bind_contract(CONTRACT_BYTES.replace(b"quality-loop", b"other-loop"))
    with pytest.raises(ContractBindingError) as captured:
        BoundContract(
            contract=changed.contract,
            contract_hash=original.contract_hash,
            source_bytes=CONTRACT_BYTES,
        )
    assert captured.value.cause is ContractBindingCause.BINDING_MISMATCH


@pytest.mark.parametrize("source", [b"[]", b'"contract"', b"1", b"true", b"null"])
def test_non_object_documents_fail_closed(source: bytes) -> None:
    """Only a JSON object can represent a canonical contract."""
    with pytest.raises(ContractBindingError) as captured:
        bind_contract(source)
    assert captured.value.cause is ContractBindingCause.INVALID_DOCUMENT


@pytest.mark.parametrize(
    ("source", "cause"),
    [
        (b"\xff", ContractBindingCause.INVALID_UTF8),
        (b"{", ContractBindingCause.INVALID_JSON),
        (b'{"id":"one","id":"two"}', ContractBindingCause.INVALID_JSON),
        (b'{"max_cost":NaN}', ContractBindingCause.INVALID_JSON),
        (b"{}", ContractBindingCause.INVALID_CONTRACT),
    ],
)
def test_invalid_sources_have_typed_causes(
    source: bytes,
    cause: ContractBindingCause,
) -> None:
    """Malformed or invalid inputs produce stable internal failure causes."""
    with pytest.raises(ContractBindingError) as captured:
        bind_contract(source)
    assert captured.value.cause is cause


@pytest.mark.parametrize(
    "source",
    [
        CONTRACT_BYTES.replace(b'"max_tokens": 10', b'"max_tokens": 0'),
        CONTRACT_BYTES.replace(b'"tests"', b'"unsupported"'),
        CONTRACT_BYTES.replace(b'"denylist": []', b'"denylist": ["src/**"]'),
    ],
)
def test_canonical_policy_validation_fails_closed(source: bytes) -> None:
    """Budget, gate, and scope violations are rejected before binding."""
    with pytest.raises(ContractBindingError) as captured:
        bind_contract(source)
    assert captured.value.cause is ContractBindingCause.INVALID_CONTRACT


def test_non_bytes_input_is_rejected_without_coercion() -> None:
    """The binding boundary never guesses an encoding for text input."""
    with pytest.raises(TypeError, match="bytes"):
        bind_contract("{}")  # type: ignore[arg-type]


def test_direct_construction_rejects_semantic_type_confusion() -> None:
    """Runtime checks protect callers outside static type checking."""
    trusted = bind_contract(CONTRACT_BYTES)
    with pytest.raises(TypeError, match="contract must be Contract"):
        BoundContract(
            contract=object(),  # type: ignore[arg-type]
            contract_hash=trusted.contract_hash,
            source_bytes=CONTRACT_BYTES,
        )
    with pytest.raises(TypeError, match="ContractHash"):
        BoundContract(
            contract=trusted.contract,
            contract_hash="bad",  # type: ignore[arg-type]
            source_bytes=CONTRACT_BYTES,
        )


def test_unexpected_validator_exception_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Canonical validator failures cannot escape as untyped exceptions."""

    def fail_validation(_document: object) -> list[str]:
        raise TypeError("validator failed")

    monkeypatch.setattr(binding_module, "validate", fail_validation)
    with pytest.raises(ContractBindingError) as captured:
        bind_contract(CONTRACT_BYTES)
    assert captured.value.cause is ContractBindingCause.INVALID_CONTRACT


def test_unexpected_model_construction_exception_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical model construction failures remain fail-closed and typed."""

    class BrokenContract:
        @classmethod
        def from_dict(cls, _document: object) -> object:
            raise ValueError("model construction failed")

    def accept_document(_document: object) -> list[str]:
        return []

    monkeypatch.setattr(binding_module, "validate", accept_document)
    monkeypatch.setattr(binding_module, "Contract", BrokenContract)
    with pytest.raises(ContractBindingError) as captured:
        bind_contract(CONTRACT_BYTES)
    assert captured.value.cause is ContractBindingCause.INVALID_CONTRACT
