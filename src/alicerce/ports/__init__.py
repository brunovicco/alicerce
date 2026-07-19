"""Provider-neutral interfaces implemented by outer adapters."""

from alicerce.ports.determinism import ClockPort, IdGeneratorPort

__all__ = ["ClockPort", "IdGeneratorPort"]
