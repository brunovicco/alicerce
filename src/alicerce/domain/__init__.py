"""Pure domain types and policies.

The domain layer has no filesystem, subprocess, network, provider, or adapter
dependencies.
"""

from alicerce.domain.contract_binding import (
    BoundContract,
    ContractBindingCause,
    ContractBindingError,
)
from alicerce.domain.contracts import FINAL_STATES, Contract, FinalState
from alicerce.domain.lifecycle import (
    LifecycleActor,
    LifecycleAdvance,
    LifecycleError,
    LifecycleErrorCause,
    LifecycleState,
    LifecycleTransition,
    RunLifecycle,
    advance_lifecycle,
    start_lifecycle,
)
from alicerce.domain.run_identity import (
    BaselineSha,
    ContractHash,
    ContractId,
    ContractVersion,
    PolicyHash,
    RunId,
    RunIdentity,
)
from alicerce.domain.state import (
    RunCheckpoint,
    StateInvariantCause,
    StateInvariantError,
    StateUpdate,
    create_initial_checkpoint,
    prepare_state_update,
)

__all__ = [
    "FINAL_STATES",
    "BaselineSha",
    "BoundContract",
    "Contract",
    "ContractBindingCause",
    "ContractBindingError",
    "ContractHash",
    "ContractId",
    "ContractVersion",
    "FinalState",
    "LifecycleActor",
    "LifecycleAdvance",
    "LifecycleError",
    "LifecycleErrorCause",
    "LifecycleState",
    "LifecycleTransition",
    "PolicyHash",
    "RunCheckpoint",
    "RunId",
    "RunIdentity",
    "RunLifecycle",
    "StateInvariantCause",
    "StateInvariantError",
    "StateUpdate",
    "advance_lifecycle",
    "create_initial_checkpoint",
    "prepare_state_update",
    "start_lifecycle",
]
