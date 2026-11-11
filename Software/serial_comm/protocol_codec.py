from __future__ import annotations

from typing import Iterable

from perfusion_app.models.protocol import ProtocolStep

import re

class ProtocolCodec:
    @staticmethod
    def manual_stimulus_command(mode: str) -> str:
        if mode == "Off":
            return "MANUAL STIMULUS OFF"
        return f"MANUAL STIMULUS {mode}"

    @staticmethod
    def parse_stream_text(raw: str) -> tuple[list[float], list[float], list[int], bool]:
        # Each analog sample arrives as "<current>,<voltage_v>,<elapsed_us>"
        # (see Perfusion_F.ino loop()). current/voltage are floats (e.g.
        # "12.34") since analogInterrupt() does a float linear calibration
        # directly to mA/V (voltage range -50V..+50V); elapsed_us is always a
        # plain integer microsecond count. Drop the first/last triplet since a
        # partial read can start or end mid-triplet.
        done = "DONE" in raw
        triples = re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+)", raw)
        if len(triples) >= 2:
            triples = triples[1:-1]
        currents = [float(a) for a, _, _ in triples]
        voltages_v = [float(b) for _, b, _ in triples]
        elapsed_us = [int(c) for _, _, c in triples]
        return currents, voltages_v, elapsed_us, done

    _TRIPLE_RE = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+)(?=[^\d.,])")

    @staticmethod
    def parse_buffered(buf: str) -> tuple[list[float], list[float], list[int], bool, str]:
        # Like parse_stream_text(), but for a running receive buffer: a triplet
        # only counts once a non-numeric character follows it (so a half-received
        # elapsed_us can't be mistaken for a complete one), nothing is thrown
        # away, and the unconsumed tail is returned to be prepended to the next read.
        done = "DONE" in buf
        currents: list[float] = []
        voltages_v: list[float] = []
        elapsed_us: list[int] = []
        end = 0
        for m in ProtocolCodec._TRIPLE_RE.finditer(buf):
            currents.append(float(m.group(1)))
            voltages_v.append(float(m.group(2)))
            elapsed_us.append(int(m.group(3)))
            end = m.end()
        rest = buf[end:]
        if len(rest) > 200:  # garbage/no triplets: don't let it grow forever
            rest = rest[-200:]
        return currents, voltages_v, elapsed_us, done, rest

    @staticmethod
    def encode_protocol_download(steps: Iterable[ProtocolStep]) -> list[str]:
        # The protocol file is duration-based (each row holds a pulse state for
        # N seconds), but the device's wire protocol only understands absolute
        # start times (see Perfusion_F.ino pulseCmd()/onCmd()/offCmd()), so
        # convert durations to a running start time here.
        lines = ["CLEAR"]
        start_ms = 0.0
        for step in steps:
            if step.pulse_on:
                if step.pulse_frequency_hz > 0:
                    lines.append(
                        f"PULSE STIMULUS {start_ms:.1f} {step.pulse_width_ms:.1f} {step.pulse_frequency_hz:.1f}"
                    )
                else:
                    # 0 Hz is the limit of a pulse train as its period -> infinity,
                    # i.e. continuously on - same convention as "MANUAL STIMULUS
                    # ON"/0 Hz in Perfusion_F.ino. The firmware's PULSE command
                    # rejects a frequency of 0 outright, so use ON instead.
                    lines.append(f"ON STIMULUS {start_ms:.1f}")
            else:
                lines.append(f"OFF STIMULUS {start_ms:.1f}")
            start_ms += step.duration_ms()

        # Bookend: without this, the protocol would stop as soon as the last
        # step *starts* rather than after it has run for its full duration,
        # and this also guarantees the stimulus ends up off once the protocol
        # finishes, regardless of what the last row's pulse state was.
        lines.append(f"OFF STIMULUS {start_ms:.1f}")
        return lines
