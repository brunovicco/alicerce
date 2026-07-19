"""Deterministic construction of immutable run identities."""

from alicerce.domain.contracts import Contract
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunIdentity,
)
from alicerce.ports.determinism import ClockPort, IdGeneratorPort


def create_run_identity(
    *,
    contract: Contract,
    contract_hash: ContractHash,
    baseline_sha: BaselineSha,
    policy_hash: PolicyHash,
    clock: ClockPort,
    id_generator: IdGeneratorPort,
) -> RunIdentity:
    """Bind canonical contract metadata and deterministic seam values."""
    canonical_contract = _require_canonical_contract(contract)
    return RunIdentity(
        run_id=id_generator.new_run_id(),
        contract_id=ContractId(canonical_contract.id),
        contract_version=ContractVersion(canonical_contract.version),
        contract_hash=contract_hash,
        baseline_sha=baseline_sha,
        policy_hash=policy_hash,
        created_at=clock.now_utc(),
    )


def _require_canonical_contract(value: object) -> Contract:
    if not isinstance(value, Contract):
        raise TypeError("contract must be the canonical Contract type")
    return value
