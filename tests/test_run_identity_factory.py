"""Tests for deterministic run identity construction."""

from datetime import UTC, datetime

import pytest
from loop_schemas.models import (  # pyright: ignore[reportMissingTypeStubs]
    Acceptance,
    Actions,
    Baseline,
    Budgets,
    Contract,
    HumanReview,
    Scope,
    Selection,
    Trigger,
)

from alicerce.application.run_identity import create_run_identity
from alicerce.domain.run_identity import BaselineSha, ContractHash, PolicyHash, RunId
from alicerce.ports.determinism import ClockPort, IdGeneratorPort

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


class FixedClock:
    """Test-only clock with a stable instant."""

    def now_utc(self) -> datetime:
        return NOW


class FixedIdGenerator:
    """Test-only identifier generator with a stable value."""

    def new_run_id(self) -> RunId:
        return RunId("run-fixed")


def _contract() -> Contract:
    return Contract(
        version="0.1.2",
        id="quality-loop",
        objective="Improve repository quality.",
        trigger=Trigger(type="manual"),
        selection=Selection(strategy="single-item"),
        baseline=Baseline(commands=("quality",)),
        acceptance=Acceptance(hard_gates=("tests",)),
        budgets=Budgets(max_tokens=1),
        scope=Scope(allowlist=("src/**",), denylist=()),
        actions=Actions(allowed=("edit",), denied=()),
        human_review=HumanReview(required=True),
    )


def _create() -> object:
    return create_run_identity(
        contract=_contract(),
        contract_hash=ContractHash("a" * 64),
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


def test_factory_uses_canonical_contract_and_deterministic_seams() -> None:
    """The factory binds canonical metadata without hidden nondeterminism."""
    identity = create_run_identity(
        contract=_contract(),
        contract_hash=ContractHash("a" * 64),
        baseline_sha=BaselineSha("b" * 40),
        policy_hash=PolicyHash("c" * 64),
        clock=FixedClock(),
        id_generator=FixedIdGenerator(),
    )
    assert identity.run_id == RunId("run-fixed")
    assert identity.contract_id.value == "quality-loop"
    assert identity.contract_version.value == "0.1.2"
    assert identity.created_at is NOW
    assert identity == _create()


def test_factory_rejects_noncanonical_contract_type() -> None:
    """A local lookalike cannot replace the canonical contract model."""
    with pytest.raises(TypeError, match="canonical Contract"):
        create_run_identity(
            contract=object(),  # type: ignore[arg-type]
            contract_hash=ContractHash("a" * 64),
            baseline_sha=BaselineSha("b" * 40),
            policy_hash=PolicyHash("c" * 64),
            clock=FixedClock(),
            id_generator=FixedIdGenerator(),
        )


@pytest.mark.xfail(
    strict=True,
    reason="canonical contract hashing is deferred; A03 and A08 remain partial",
)
def test_factory_rejects_hash_not_derived_from_contract() -> None:
    """Known gap: the supplied contract digest is not yet recomputed."""
    with pytest.raises(ValueError, match="contract hash"):
        create_run_identity(
            contract=_contract(),
            contract_hash=ContractHash("f" * 64),
            baseline_sha=BaselineSha("b" * 40),
            policy_hash=PolicyHash("c" * 64),
            clock=FixedClock(),
            id_generator=FixedIdGenerator(),
        )
