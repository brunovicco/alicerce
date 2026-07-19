"""Trusted binding between exact contract bytes and the canonical model."""

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from loop_schemas.validate_contract import (  # pyright: ignore[reportMissingTypeStubs]
    validate,
)

from alicerce.domain.contracts import Contract
from alicerce.domain.run_identity import ContractHash


class ContractBindingCause(StrEnum):
    """Internal fail-closed causes for contract binding."""

    INVALID_UTF8 = "invalid_utf8"
    INVALID_JSON = "invalid_json"
    INVALID_DOCUMENT = "invalid_document"
    INVALID_CONTRACT = "invalid_contract"
    BINDING_MISMATCH = "binding_mismatch"


class ContractBindingError(ValueError):
    """Raised when exact source bytes cannot produce a trusted binding."""

    def __init__(self, cause: ContractBindingCause, detail: str) -> None:
        """Record a typed cause without retaining source content."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


class _DuplicateKeyError(ValueError):
    """Signal an ambiguous JSON object during decoding."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def _parse_contract(source: object) -> Contract:
    source_bytes = _require_instance(source, name="source_bytes", expected=bytes)
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractBindingError(
            ContractBindingCause.INVALID_UTF8,
            "contract source must be valid UTF-8",
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonfinite_number,
        )
    except (json.JSONDecodeError, _DuplicateKeyError, ValueError) as error:
        raise ContractBindingError(
            ContractBindingCause.INVALID_JSON,
            str(error),
        ) from error
    if not isinstance(decoded, dict):
        raise ContractBindingError(
            ContractBindingCause.INVALID_DOCUMENT,
            "top-level JSON value must be an object",
        )

    document = cast(dict[str, Any], decoded)
    try:
        errors = validate(document)
    except (KeyError, TypeError, ValueError) as error:
        raise ContractBindingError(
            ContractBindingCause.INVALID_CONTRACT,
            str(error),
        ) from error
    if errors:
        raise ContractBindingError(
            ContractBindingCause.INVALID_CONTRACT,
            "; ".join(errors),
        )
    try:
        return Contract.from_dict(document)
    except (KeyError, TypeError, ValueError) as error:
        raise ContractBindingError(
            ContractBindingCause.INVALID_CONTRACT,
            str(error),
        ) from error


def _hash_contract(source_bytes: bytes) -> ContractHash:
    return ContractHash(hashlib.sha256(source_bytes).hexdigest())


@dataclass(frozen=True, slots=True)
class BoundContract:
    """Canonical contract proven to correspond to exact source bytes."""

    contract: Contract
    contract_hash: ContractHash
    source_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        """Revalidate correspondence even during direct construction."""
        contract = _require_instance(self.contract, name="contract", expected=Contract)
        contract_hash = _require_instance(
            self.contract_hash,
            name="contract_hash",
            expected=ContractHash,
        )
        parsed = _parse_contract(self.source_bytes)
        expected_hash = _hash_contract(self.source_bytes)
        if parsed != contract or expected_hash != contract_hash:
            raise ContractBindingError(
                ContractBindingCause.BINDING_MISMATCH,
                "contract, hash, and source bytes do not correspond",
            )

    @classmethod
    def from_json_bytes(cls, source_bytes: bytes) -> "BoundContract":
        """Build a binding from exact validated UTF-8 JSON bytes."""
        contract = _parse_contract(source_bytes)
        return cls(
            contract=contract,
            contract_hash=_hash_contract(source_bytes),
            source_bytes=source_bytes,
        )
