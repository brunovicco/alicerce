"""Provider-neutral interfaces implemented by outer adapters."""

from alicerce.ports.determinism import ClockPort, IdGeneratorPort
from alicerce.ports.state_store import StateStoreError, StateStoreErrorCause, StateStorePort
from alicerce.ports.workspace import (
    WorkspaceError,
    WorkspaceErrorCause,
    WorkspaceIdGeneratorPort,
    WorkspacePort,
)

__all__ = [
    "ClockPort",
    "IdGeneratorPort",
    "StateStoreError",
    "StateStoreErrorCause",
    "StateStorePort",
    "WorkspaceError",
    "WorkspaceErrorCause",
    "WorkspaceIdGeneratorPort",
    "WorkspacePort",
]
