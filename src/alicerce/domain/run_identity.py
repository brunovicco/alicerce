"""Immutable values that bind one run to its trusted inputs."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

_RUN_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z")
_BASELINE_SHA_PATTERN: Final = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty and have no surrounding whitespace")
    return value


def _require_pattern(value: object, *, name: str, pattern: re.Pattern[str]) -> str:
    text = _require_text(value, name=name)
    if pattern.fullmatch(text) is None:
        raise ValueError(f"{name} has an invalid format")
    return text


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


@dataclass(frozen=True, slots=True)
class RunId:
    """Opaque, path-safe identifier for one run."""

    value: str

    def __post_init__(self) -> None:
        """Reject unsafe or noncanonical run identifiers."""
        _require_pattern(self.value, name="run_id", pattern=_RUN_ID_PATTERN)

    def __str__(self) -> str:
        """Return the wrapped identifier."""
        return self.value


@dataclass(frozen=True, slots=True)
class ContractId:
    """Semantic wrapper for a canonical contract identifier."""

    value: str

    def __post_init__(self) -> None:
        """Reject invalid canonical contract identifiers."""
        _require_text(self.value, name="contract_id")

    def __str__(self) -> str:
        """Return the wrapped identifier."""
        return self.value


@dataclass(frozen=True, slots=True)
class ContractVersion:
    """Semantic wrapper for a canonical contract version."""

    value: str

    def __post_init__(self) -> None:
        """Reject invalid canonical contract versions."""
        _require_text(self.value, name="contract_version")

    def __str__(self) -> str:
        """Return the wrapped version."""
        return self.value


@dataclass(frozen=True, slots=True)
class ContractHash:
    """Lowercase SHA-256 digest of canonical contract bytes."""

    value: str

    def __post_init__(self) -> None:
        """Reject incomplete or noncanonical digests."""
        _require_pattern(self.value, name="contract_hash", pattern=_SHA256_PATTERN)

    def __str__(self) -> str:
        """Return the wrapped digest."""
        return self.value


@dataclass(frozen=True, slots=True)
class BaselineSha:
    """Complete 40- or 64-character baseline object identifier."""

    value: str

    def __post_init__(self) -> None:
        """Reject abbreviated or noncanonical object identifiers."""
        _require_pattern(self.value, name="baseline_sha", pattern=_BASELINE_SHA_PATTERN)

    def __str__(self) -> str:
        """Return the wrapped object identifier."""
        return self.value


@dataclass(frozen=True, slots=True)
class PolicyHash:
    """Lowercase SHA-256 digest of the trusted policy bundle."""

    value: str

    def __post_init__(self) -> None:
        """Reject incomplete or noncanonical digests."""
        _require_pattern(self.value, name="policy_hash", pattern=_SHA256_PATTERN)

    def __str__(self) -> str:
        """Return the wrapped digest."""
        return self.value


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Immutable binding between a run and its trusted inputs."""

    run_id: RunId
    contract_id: ContractId
    contract_version: ContractVersion
    contract_hash: ContractHash
    baseline_sha: BaselineSha
    policy_hash: PolicyHash
    created_at: datetime

    def __post_init__(self) -> None:
        """Reject type confusion and timestamps outside UTC."""
        _require_instance(self.run_id, name="run_id", expected=RunId)
        _require_instance(self.contract_id, name="contract_id", expected=ContractId)
        _require_instance(
            self.contract_version,
            name="contract_version",
            expected=ContractVersion,
        )
        _require_instance(self.contract_hash, name="contract_hash", expected=ContractHash)
        _require_instance(self.baseline_sha, name="baseline_sha", expected=BaselineSha)
        _require_instance(self.policy_hash, name="policy_hash", expected=PolicyHash)
        created_at = _require_instance(self.created_at, name="created_at", expected=datetime)
        if created_at.tzinfo is not UTC:
            raise ValueError("created_at must use UTC timezone")
