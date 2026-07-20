"""Fail-closed identity validation before a persisted run may resume."""

from enum import StrEnum

from alicerce.domain.contract_binding import BoundContract
from alicerce.domain.lifecycle import LifecycleState
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
)
from alicerce.domain.state import RunCheckpoint
from alicerce.ports.state_store import StateStorePort


class ResumeErrorCause(StrEnum):
    """Stable causes that prevent trusted continuation of a persisted run."""

    NOT_FOUND = "not_found"
    RUN_MISMATCH = "run_mismatch"
    CONTRACT_MISMATCH = "contract_mismatch"
    BASELINE_MISMATCH = "baseline_mismatch"
    POLICY_MISMATCH = "policy_mismatch"
    TERMINAL_RUN = "terminal_run"


class ResumeError(RuntimeError):
    """Raised when a persisted run is not safe to continue."""

    def __init__(self, cause: ResumeErrorCause, detail: str) -> None:
        """Record a stable typed cause."""
        self.cause = cause
        super().__init__(f"{cause.value}: {detail}")


def _require_instance[ValueT](value: object, *, name: str, expected: type[ValueT]) -> ValueT:
    if not isinstance(value, expected):
        raise TypeError(f"{name} must be {expected.__name__}")
    return value


def load_run_for_resume(
    *,
    run_id: RunId,
    bound_contract: BoundContract,
    baseline_sha: BaselineSha,
    policy_hash: PolicyHash,
    state_store: StateStorePort,
) -> RunCheckpoint:
    """Load one nonterminal checkpoint only when trusted bindings still match."""
    trusted_run_id = _require_instance(run_id, name="run_id", expected=RunId)
    trusted_contract = _require_instance(
        bound_contract,
        name="bound_contract",
        expected=BoundContract,
    )
    trusted_baseline = _require_instance(
        baseline_sha,
        name="baseline_sha",
        expected=BaselineSha,
    )
    trusted_policy = _require_instance(
        policy_hash,
        name="policy_hash",
        expected=PolicyHash,
    )

    loaded = state_store.load(trusted_run_id)
    if loaded is None:
        raise ResumeError(ResumeErrorCause.NOT_FOUND, trusted_run_id.value)
    checkpoint = _require_instance(
        loaded,
        name="loaded checkpoint",
        expected=RunCheckpoint,
    )
    identity = checkpoint.identity
    if identity.run_id != trusted_run_id:
        raise ResumeError(
            ResumeErrorCause.RUN_MISMATCH,
            "persisted checkpoint does not match the requested run",
        )

    canonical = trusted_contract.contract
    if (
        identity.contract_id != ContractId(canonical.id)
        or identity.contract_version != ContractVersion(canonical.version)
        or identity.contract_hash != trusted_contract.contract_hash
    ):
        raise ResumeError(
            ResumeErrorCause.CONTRACT_MISMATCH,
            "persisted contract binding has changed",
        )
    if identity.baseline_sha != trusted_baseline:
        raise ResumeError(
            ResumeErrorCause.BASELINE_MISMATCH,
            "persisted baseline binding has changed",
        )
    if identity.policy_hash != trusted_policy:
        raise ResumeError(
            ResumeErrorCause.POLICY_MISMATCH,
            "persisted policy binding has changed",
        )
    if checkpoint.lifecycle.state is LifecycleState.COMPLETED:
        raise ResumeError(
            ResumeErrorCause.TERMINAL_RUN,
            "completed run cannot resume working-state execution",
        )
    return checkpoint
