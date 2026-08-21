"""Synthetic sensor signal generator.

Fake sensor data for the mock uC: a couple of sine tones plus noise, just
enough structure to make the time-domain plot (and FFT) actually mean
something.
"""

from __future__ import annotations

import numpy as np

EXPECTED_SAMPLES_PER_FRAME = 20000
SAMPLE_RATE_HZ = 2_000_000  # 2 Msps, per the challenge spec.

_DEFAULT_AMPLITUDE = 1_000_000  # stays well inside int32 range


class SignalGenerator:
    # Keeps a running sample index so phase stays continuous across frames -
    # no discontinuity/click at frame boundaries in the plot or FFT.

    def __init__(
        self,
        samples_per_frame: int = EXPECTED_SAMPLES_PER_FRAME,
        sample_rate_hz: int = SAMPLE_RATE_HZ,
        amplitude: int = _DEFAULT_AMPLITUDE,
        tones_hz: tuple[float, ...] = (5_000.0, 50_000.0),
        noise_fraction: float = 0.05,
        seed: int | None = None,
    ) -> None:
        """Configures the signal generator.

        Args:
            samples_per_frame: Number of samples produced by each
                `next_frame()` call.
            sample_rate_hz: Sampling rate used to generate the time axis,
                in Hz.
            amplitude: Total peak amplitude shared across all tones, in raw
                sample units.
            tones_hz: Frequencies (Hz) of the sine tones summed into the
                signal.
            noise_fraction: Gaussian noise standard deviation, as a fraction
                of `amplitude`.
            seed: Optional RNG seed for reproducible noise; `None` uses
                random entropy.
        """
        self._samples_per_frame = samples_per_frame
        self._sample_rate_hz = sample_rate_hz
        self._amplitude = amplitude
        self._tones_hz = tones_hz
        self._noise_fraction = noise_fraction
        self._rng = np.random.default_rng(seed)
        self._sample_index = 0

    def next_frame(self) -> bytes:
        """Generates the next frame of synthetic signal data.

        Advances the internal sample index so phase stays continuous across
        frames (no discontinuity/click at frame boundaries in the plot or
        FFT).

        Returns:
            Raw int32_le bytes, `samples_per_frame * 4` bytes long, ready to
            send over the WebSocket.
        """
        n = self._samples_per_frame
        start = self._sample_index
        t = np.arange(start, start + n, dtype=np.float64) / self._sample_rate_hz
        self._sample_index += n

        waveform = np.zeros(n, dtype=np.float64)
        per_tone_amplitude = self._amplitude / max(len(self._tones_hz), 1)
        for freq in self._tones_hz:
            waveform += per_tone_amplitude * np.sin(2.0 * np.pi * freq * t)

        if self._noise_fraction > 0.0:
            noise = self._rng.normal(
                0.0, self._amplitude * self._noise_fraction, size=n
            )
            waveform += noise

        samples = waveform.astype("<i4")
        return samples.tobytes()
