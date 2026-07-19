"""Tests for deterministic run identity construction."""

from datetime import UTC, datetime

import pytest

from alicerce.application.contract_binding import bind_contract
from alicerce.application.run_identity import create_run_identity
from alicerce.domain.run_identity import BaselineSha, PolicyHash, RunId
from alicerce.ports.determinism import ClockPort, IdGeneratorPort

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
CONTRACT_BYTES = b"""{
  "version": "0.1.2",
  "id": "quality-loop",
  "objective": "Improve repository quality.",
  "trigger": {"type": "manual"},
  "selection": {"strategy": "single-item"},
  "baseline": {"commands": ["quality"]},
  "acceptance": {"hard_gates": ["tests"]},
  "budgets": {"max_tokens": 1},
  "scope": {"allowlist": ["src/**"], "denylist": []},
  "actions": {"allowed": ["edit"], "denied": []},
  "human_review": {"required": true}
}"""


class FixedClock:
    """Test-only clock with a stable instant."""

    def now_utc(self) -> datetime:
        return NOW


class FixedIdGenerator:
    """Test-only identifier generator with a stable value."""

    def new_run_id(self) -> RunId:
        return RunId("run-fixed")


def _create() -> object:
    return create_run_identity(
        bound_contract=bind_contract(CONTRACT_BYTES),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        clock=FixedClock(),
        id_generator=FixedIdGenerator(),
    )


def test_test_doubles_conform_to_structural_ports() -> None:
    """Inline deterministic doubles satisfy the declared seams statically."""
    clock: ClockPort = FixedClock()
    generator: IdGeneratorPort = FixedIdGenerator()
    assert clock.now_utc() is NOW
    assert generator.new_run_id() == RunId("run-fixed")


def test_factory_uses_bound_contract_and_deterministic_seams() -> None:
    """The factory binds proven contract metadata without hidden nondeterminism."""
    bound_contract = bind_contract(CONTRACT_BYTES)
    identity = create_run_identity(
        bound_contract=bound_contract,
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        clock=FixedClock(),
        id_generator=FixedIdGenerator(),
    )
    assert identity.run_id == RunId("run-fixed")
    assert identity.contract_id.value == "quality-loop"
    assert identity.contract_version.value == "0.1.2"
    assert identity.contract_hash == bound_contract.contract_hash
    assert identity.created_at is NOW
    assert identity == _create()


def test_factory_rejects_unbound_contract_input() -> None:
    """A canonical contract alone cannot bypass exact-byte binding."""
    with pytest.raises(TypeError, match="BoundContract"):
        create_run_identity(
            bound_contract=object(),  # type: ignore[arg-type]
            baseline_sha=BaselineSha("b" * 40),
            policy_hash=PolicyHash("c" * 64),
            clock=FixedClock(),
            id_generator=FixedIdGenerator(),
        )


def test_factory_has_no_independent_contract_hash_parameter() -> None:
    """Callers cannot pair a bound contract with an unrelated digest."""
    with pytest.raises(TypeError, match="contract_hash"):
        create_run_identity(
            bound_contract=bind_contract(CONTRACT_BYTES),
            contract_hash="f" * 64,  # type: ignore[call-arg]
            baseline_sha=BaselineSha("b" * 40),
            policy_hash=PolicyHash("c" * 64),
            clock=FixedClock(),
            id_generator=FixedIdGenerator(),
        )
