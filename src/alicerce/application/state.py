"""Application facade for immutable run state operations."""

from alicerce.domain.state import (
    RunCheckpoint,
    StateUpdate,
    create_initial_checkpoint,
    prepare_state_update,
)

__all__ = [
    "RunCheckpoint",
    "StateUpdate",
    "create_initial_checkpoint",
    "prepare_state_update",
]
