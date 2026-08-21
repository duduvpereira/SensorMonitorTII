"""Tests for hashing."""

import xxhash

from backend.app.hashing import hash_frame


def test_hash_frame_matches_reference():
    payload = b"hello world"
    expected = xxhash.xxh3_128(payload).hexdigest()
    assert hash_frame(payload) == expected


def test_hash_frame_is_32_hex_chars():
    # XXH3_128 => 128 bits => 32 hex characters.
    result = hash_frame(b"some binary payload")
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_frame_is_deterministic():
    payload = b"\x00\x01\x02\x03" * 100
    assert hash_frame(payload) == hash_frame(payload)


def test_hash_frame_differs_for_different_input():
    assert hash_frame(b"aaaa") != hash_frame(b"aaab")


def test_hash_frame_empty_payload():
    # Should not raise, and should match the library's empty-input hash.
    assert hash_frame(b"") == xxhash.xxh3_128(b"").hexdigest()
