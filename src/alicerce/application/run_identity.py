"""Deterministic construction of immutable run identities."""

from alicerce.domain.contract_binding import BoundContract
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunIdentity,
)
from alicerce.ports.determinism import ClockPort, IdGeneratorPort


def create_run_identity(
    *,
    bound_contract: BoundContract,
    baseline_sha: BaselineSha,
    policy_hash: PolicyHash,
    clock: ClockPort,
    id_generator: IdGeneratorPort,
) -> RunIdentity:
    """Bind canonical contract metadata and deterministic seam values."""
    trusted_binding = _require_bound_contract(bound_contract)
    canonical_contract = trusted_binding.contract
    return RunIdentity(
        run_id=id_generator.new_run_id(),
        contract_id=ContractId(canonical_contract.id),
        contract_version=ContractVersion(canonical_contract.version),
        contract_hash=trusted_binding.contract_hash,
        baseline_sha=baseline_sha,
        policy_hash=policy_hash,
        created_at=clock.now_utc(),
    )


def _require_bound_contract(value: object) -> BoundContract:
    if not isinstance(value, BoundContract):
        raise TypeError("bound_contract must be BoundContract")
    return value
