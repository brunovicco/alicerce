"""Contract tests for the pinned canonical schemas boundary."""

import loop_schemas.models as canonical  # pyright: ignore[reportMissingTypeStubs]

from alicerce.domain import contracts


def test_domain_reexports_the_canonical_contract_objects_by_identity() -> None:
    """Alicerce never substitutes equivalent local contract types."""
    assert contracts.Actions is canonical.Actions
    assert contracts.Contract is canonical.Contract
    assert contracts.FinalState is canonical.FinalState
    assert contracts.FINAL_STATES is canonical.FINAL_STATES


def test_all_eight_canonical_final_states_remain_unchanged() -> None:
    """The pinned schemas package remains the sole final-state authority."""
    assert contracts.FINAL_STATES == (
        "SUCCEEDED",
        "NO_OP",
        "NO_PROGRESS",
        "VERIFY_FAILED",
        "POLICY_BLOCKED",
        "BUDGET_EXCEEDED",
        "ESCALATED",
        "INFRA_FAILED",
    )
