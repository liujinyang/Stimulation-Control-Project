from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProtocolStep:
    """One segment of a stimulation protocol: hold a pulse state for a duration.

    Units are fixed (seconds for duration, milliseconds for pulse width) since
    the protocol file no longer lets each row choose its own units.
    """

    duration_s: float
    pulse_on: bool
    pulse_width_ms: float = 0.0
    pulse_frequency_hz: float = 0.0

    def duration_ms(self) -> float:
        return self.duration_s * 1000.0
