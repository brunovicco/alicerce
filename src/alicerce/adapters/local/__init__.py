"""Local-only adapters authorized for Phase 2A."""

from alicerce.adapters.local.command_executor import LocalCommandExecutor, TrustedExecutable
from alicerce.adapters.local.git_workspace import LocalGitWorkspace
from alicerce.adapters.local.sqlite_state_store import SQLiteStateStore
from alicerce.adapters.local.state_serialization import (
    STATE_FORMAT_VERSION,
    StateSerializationError,
    deserialize_checkpoint,
    deserialize_run_identity,
    deserialize_transition,
    serialize_checkpoint,
    serialize_run_identity,
    serialize_transition,
)

__all__ = [
    "STATE_FORMAT_VERSION",
    "LocalCommandExecutor",
    "LocalGitWorkspace",
    "SQLiteStateStore",
    "StateSerializationError",
    "TrustedExecutable",
    "deserialize_checkpoint",
    "deserialize_run_identity",
    "deserialize_transition",
    "serialize_checkpoint",
    "serialize_run_identity",
    "serialize_transition",
]
