"""Provider-neutral seams for deterministic identity creation."""

from datetime import datetime
from typing import Protocol

from alicerce.domain.run_identity import RunId


class ClockPort(Protocol):
    """Supply the current UTC instant."""

    def now_utc(self) -> datetime:
        """Return a timezone-aware UTC instant."""
        ...


class IdGeneratorPort(Protocol):
    """Supply a new opaque run identifier."""

    def new_run_id(self) -> RunId:
        """Return a new valid run identifier."""
        ...
