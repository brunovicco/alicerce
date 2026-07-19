"""Application entry point for trusted contract binding."""

from alicerce.domain.contract_binding import BoundContract


def bind_contract(source_bytes: bytes) -> BoundContract:
    """Validate exact JSON bytes and bind them to a canonical contract."""
    return BoundContract.from_json_bytes(source_bytes)
