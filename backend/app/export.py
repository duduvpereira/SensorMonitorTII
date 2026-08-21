"""Export serialisation.

Turns a list of ProcessedFrame objects (as retained in the ring buffer) into
CSV or JSON for download. Per the challenge's optional export feature, the
exported data is the *received data* held in the buffer — i.e. the decimated
plot samples plus each frame's metadata (number, timestamp, sample count,
hash, estimated rate).

Note on decimation: the buffer stores the plot-decimated samples (~2000 per
frame), not the raw 20000, to keep memory bounded. Exporting the decimated
signal is a deliberate trade-off, documented in the README; the spec itself
notes the raw file size "may be large" and suggests limiting the export.

These functions are pure (list in, string out) so they're unit-testable
without any web layer or file I/O.
"""

from __future__ import annotations

import csv
import io
import json

from .models import ProcessedFrame


def frames_to_json(frames: list[ProcessedFrame]) -> str:
    """Serialises frames to a JSON string.

    Structure: a top-level object with the frame count and an array of frame
    objects (each the frame's full to_dict(), including plot_samples). JSON is
    the richer format — it preserves the nested per-frame sample arrays.
    """
    payload = {
        "frame_count": len(frames),
        "frames": [f.to_dict() for f in frames],
    }
    return json.dumps(payload, indent=2)


def frames_to_csv(frames: list[ProcessedFrame]) -> str:
    """Serialises frames to a CSV string.

    CSV is flat, so one row per (frame, sample) pair: the frame metadata is
    repeated on each of that frame's sample rows, with the sample's index and
    value. This keeps the file openable in any spreadsheet while still
    carrying both the metadata and the decimated signal.

    Columns: frame_number, timestamp, sample_count, is_valid, frame_hash,
             sample_rate, sample_index, sample_value
    """
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "frame_number",
            "timestamp",
            "sample_count",
            "is_valid",
            "frame_hash",
            "sample_rate",
            "sample_index",
            "sample_value",
        ]
    )

    for f in frames:
        base = [
            f.frame_number,
            f.timestamp,
            f.sample_count,
            f.is_valid,
            f.frame_hash,
            "" if f.sample_rate is None else f.sample_rate,
        ]
        if f.plot_samples:
            for i, value in enumerate(f.plot_samples):
                writer.writerow(base + [i, value])
        else:
            # Frame with no plot samples (e.g. throttled/corrupt): still emit a
            # metadata row so the frame isn't silently dropped from the export.
            writer.writerow(base + ["", ""])

    return out.getvalue()