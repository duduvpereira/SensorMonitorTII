"""Binary frame parsing.

Each WebSocket packet from the microcontroller carries a raw binary payload
of int32 little-endian samples (one frame). Parsing is done with NumPy so it
stays fast enough for the ~100 frames/s stream (2 Msps / 20000 samples).
"""

from __future__ import annotations

import numpy as np

# One sample is a 32-bit little-endian signed integer.
SAMPLE_DTYPE = np.dtype("<i4")
SAMPLE_SIZE_BYTES = SAMPLE_DTYPE.itemsize  # 4

# Expected number of samples in a well-formed frame.
EXPECTED_SAMPLES_PER_FRAME = 20000


def parse_frame(payload: bytes) -> np.ndarray:
    """Parses a raw binary payload into an array of int32 samples.

    Args:
        payload: Raw bytes of one WebSocket frame.

    Returns:
        A 1-D NumPy array (dtype int32) viewing the samples. The array does
        not own the buffer copy beyond what np.frombuffer provides, so callers
        that need to mutate or retain it long-term should copy.

    Raises:
        ValueError: If the payload length is not a whole number of samples
            (i.e. not a multiple of 4 bytes). A truncated sample means the
            payload is corrupt at the byte level, which is distinct from a
            frame simply having the wrong *number* of (whole) samples — the
            latter is handled by the validator, not here.
    """
    if len(payload) % SAMPLE_SIZE_BYTES != 0:
        raise ValueError(
            f"Payload length {len(payload)} bytes is not a multiple of "
            f"{SAMPLE_SIZE_BYTES} (one int32 sample)."
        )
    return np.frombuffer(payload, dtype=SAMPLE_DTYPE)


def count_samples(payload: bytes) -> int:
    """Returns how many whole int32 samples the payload contains.

    This is a cheap byte-length division; it does not allocate an array, so
    it is safe to call on the hot path just to log/validate the sample count.
    """
    return len(payload) // SAMPLE_SIZE_BYTES
