"""Pure domain types and policies.

The domain layer has no filesystem, subprocess, network, provider, or adapter
dependencies.
"""

from alicerce.domain.command import (
    CommandAction,
    CommandLimits,
    CommandRequest,
    EnvironmentVariable,
    ExecutableId,
    ExecutionResult,
    ExecutionTermination,
    NetworkPolicy,
    WorkingDirectory,
)
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
from alicerce.domain.workspace import (
    CandidateIdentity,
    CandidateSha,
    WorkspaceId,
    WorkspaceIdentity,
    bind_candidate,
)

__all__ = [
    "FINAL_STATES",
    "BaselineSha",
    "BoundContract",
    "CandidateIdentity",
    "CandidateSha",
    "CommandAction",
    "CommandLimits",
    "CommandRequest",
    "Contract",
    "ContractBindingCause",
    "ContractBindingError",
    "ContractHash",
    "ContractId",
    "ContractVersion",
    "EnvironmentVariable",
    "ExecutableId",
    "ExecutionResult",
    "ExecutionTermination",
    "FinalState",
    "LifecycleActor",
    "LifecycleAdvance",
    "LifecycleError",
    "LifecycleErrorCause",
    "LifecycleState",
    "LifecycleTransition",
    "NetworkPolicy",
    "PolicyHash",
    "RunCheckpoint",
    "RunId",
    "RunIdentity",
    "RunLifecycle",
    "StateInvariantCause",
    "StateInvariantError",
    "StateUpdate",
    "WorkingDirectory",
    "WorkspaceId",
    "WorkspaceIdentity",
    "advance_lifecycle",
    "bind_candidate",
    "create_initial_checkpoint",
    "prepare_state_update",
    "start_lifecycle",
]
