"""Contract tests for the pinned canonical schemas boundary."""

from dataclasses import fields
from typing import get_args

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


def test_canonical_command_result_exposes_the_v0_2_integrity_bindings() -> None:
    """The pinned package supplies the exact command-evidence shape needed by A08."""
    assert tuple(field.name for field in fields(canonical.CommandResult)) == (
        "command",
        "termination",
        "exit_code",
        "stdout_sha256",
        "stderr_sha256",
        "specification_sha256",
        "duration_s",
    )
    assert set(get_args(canonical.ExecutionTermination)) == {
        "EXITED",
        "TIMED_OUT",
        "CANCELLED",
        "OUTPUT_LIMIT",
    }

    exited = canonical.CommandResult(
        command="uv run pytest",
        termination="EXITED",
        exit_code=0,
        stdout_sha256="a" * 64,
        stderr_sha256="b" * 64,
        specification_sha256="c" * 64,
        duration_s=1.25,
    )
    timed_out = canonical.CommandResult(
        command="uv run pytest",
        termination="TIMED_OUT",
        exit_code=None,
        stdout_sha256="d" * 64,
        stderr_sha256="e" * 64,
        specification_sha256="f" * 64,
        duration_s=10.0,
    )

    assert exited.exit_code == 0
    assert timed_out.exit_code is None
