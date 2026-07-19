"""Package metadata tests."""

from __future__ import annotations

import alicerce


def test_package_exposes_version() -> None:
    """The initial package exposes one stable public metadata value."""
    assert alicerce.__version__ == "0.1.0"
    assert alicerce.__all__ == ["__version__"]
