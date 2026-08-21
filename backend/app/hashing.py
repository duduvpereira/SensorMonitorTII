"""Frame hashing.

Hashes the *raw binary payload* of a frame (not the parsed samples), so the
hash matches exactly what was received on the wire regardless of how it's
later parsed.
"""

from __future__ import annotations

import xxhash


def hash_frame(payload: bytes) -> str:
    """Computes the XXH3_128 hash of a raw frame payload.

    Args:
        payload: Raw bytes of one WebSocket frame.

    Returns:
        The 128-bit hash as a 32-character lowercase hex string
        (e.g. "e2966f42b51a85b2e85f9562b284ff9d").
    """
    return xxhash.xxh3_128(payload).hexdigest()
