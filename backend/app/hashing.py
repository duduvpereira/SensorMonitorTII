"""Frame hashing.

The challenge requires an XXH3_128 hash of the *raw binary payload* of every
frame (not of the parsed samples). Computing it on the raw bytes avoids any
dependency on endianness/parsing and matches exactly what was received on the
wire, which is what a downstream integrity check would want.
"""

from __future__ import annotations

import xxhash


def hash_frame(payload: bytes) -> str:
    """Computes the XXH3_128 hash of a raw frame payload.

    Args:
        payload: Raw bytes of one WebSocket frame.

    Returns:
        The 128-bit hash as a 32-character lowercase hex string, matching the
        format shown in the challenge's log example
        (e.g. "e2966f42b51a85b2e85f9562b284ff9d").
    """
    return xxhash.xxh3_128(payload).hexdigest()
