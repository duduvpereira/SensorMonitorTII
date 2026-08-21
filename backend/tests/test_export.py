"""Tests for export serialisation (CSV and JSON)."""

import csv
import io
import json

from backend.app.export import frames_to_csv, frames_to_json
from backend.app.models import ProcessedFrame


def _frame(
    n,
    plot_samples=None,
    sample_rate=None,
    is_valid=True,
    sample_count=20000,
    power_db=None,
):
    return ProcessedFrame(
        frame_number=n,
        timestamp="2026-08-20 18:00:00",
        sample_count=sample_count,
        expected_samples=20000,
        is_valid=is_valid,
        frame_hash="a" * 32,
        sample_rate=sample_rate,
        plot_samples=plot_samples or [],
        power_db=power_db,
    )


# ---- JSON ----

def test_json_empty():
    out = json.loads(frames_to_json([]))
    assert out["frame_count"] == 0
    assert out["frames"] == []


def test_json_structure():
    frames = [_frame(1, plot_samples=[1.0, 2.0], sample_rate=2_000_000.0)]
    out = json.loads(frames_to_json(frames))
    assert out["frame_count"] == 1
    f = out["frames"][0]
    assert f["frame_number"] == 1
    assert f["plot_samples"] == [1.0, 2.0]
    assert f["frame_hash"] == "a" * 32
    assert "log_line" in f


def test_json_is_valid_json():
    frames = [_frame(1), _frame(2)]
    # Should not raise.
    json.loads(frames_to_json(frames))


# ---- CSV ----

def test_csv_header():
    out = frames_to_csv([])
    reader = csv.reader(io.StringIO(out))
    header = next(reader)
    assert header == [
        "frame_number",
        "timestamp",
        "sample_count",
        "is_valid",
        "frame_hash",
        "sample_rate",
        "power_db",
        "sample_index",
        "sample_value",
    ]


def test_csv_one_row_per_sample():
    frames = [_frame(1, plot_samples=[10.0, 20.0, 30.0])]
    reader = list(csv.reader(io.StringIO(frames_to_csv(frames))))
    # 1 header + 3 sample rows.
    assert len(reader) == 4
    # Sample index/value on the data rows.
    assert reader[1][-2:] == ["0", "10.0"]
    assert reader[3][-2:] == ["2", "30.0"]


def test_csv_frame_without_samples_still_emitted():
    # A frame with no plot samples (throttled) still gets one metadata row.
    frames = [_frame(1, plot_samples=[])]
    reader = list(csv.reader(io.StringIO(frames_to_csv(frames))))
    assert len(reader) == 2  # header + 1 metadata row
    assert reader[1][0] == "1"
    assert reader[1][-2:] == ["", ""]  # empty sample index/value


def test_csv_metadata_repeated_per_sample():
    frames = [_frame(7, plot_samples=[1.0, 2.0], sample_rate=1_500_000.0)]
    reader = list(csv.reader(io.StringIO(frames_to_csv(frames))))
    # Both sample rows carry the same frame_number (7) and hash.
    assert reader[1][0] == "7"
    assert reader[2][0] == "7"
    assert reader[1][4] == "a" * 32


def test_csv_invalid_frame_flag():
    frames = [_frame(1, plot_samples=[1.0], is_valid=False, sample_count=19999)]
    reader = list(csv.reader(io.StringIO(frames_to_csv(frames))))
    # is_valid column is False, sample_count reflects the wrong count.
    assert reader[1][3] == "False"
    assert reader[1][2] == "19999"


def test_csv_power_db_column():
    frames = [_frame(1, plot_samples=[1.0], power_db=-42.5)]
    reader = list(csv.reader(io.StringIO(frames_to_csv(frames))))
    # power_db sits right after sample_rate in the header.
    assert reader[1][6] == "-42.5"


def test_csv_missing_power_db_is_blank():
    frames = [_frame(1, plot_samples=[1.0], power_db=None)]
    reader = list(csv.reader(io.StringIO(frames_to_csv(frames))))
    assert reader[1][6] == ""