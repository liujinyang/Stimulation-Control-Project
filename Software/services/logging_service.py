from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Windows forbids these in filenames; swap each for "_" so an arbitrary
# protocol name can't produce an invalid or path-escaping filename.
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class CsvLogger:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._fh = None
        self._elapsed_offset_us: int | None = None
        self._last_relative_elapsed_us: int | None = None
        self._session_ended = False
        self._started_at = 0.0
        self._pc_mode = False
        self._pc_prev_t: float | None = None
        self._pc_t0: float | None = None
        self._pending: list = []

    @property
    def is_active(self) -> bool:
        return self._fh is not None

    def start(self, protocol_name: str = "") -> Path:
        self.stop()  # close any previous file first instead of leaking the handle
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        name = _UNSAFE_FILENAME_CHARS.sub("_", protocol_name).strip().strip(".")
        filename = f"{timestamp}_{name}.csv" if name else f"{timestamp}.csv"
        path = self.base_dir / filename
        self._fh = path.open("w", encoding="utf-8")
        self._fh.write("time_ms,current_mA,voltage_V\n")
        self._elapsed_offset_us = None
        self._last_relative_elapsed_us = None
        self._session_ended = False
        self._started_at = time.monotonic()
        self._pc_mode = False
        self._pc_prev_t = None
        self._pc_t0 = None
        self._pending = []
        return path

    def write_samples(
        self, samples: Iterable[float], voltages_v: Iterable[float], elapsed_us: Iterable[int]
    ) -> None:
        if not self._fh or self._session_ended:
            return
        # elapsed_us counts up from 0 the moment the device actually starts its
        # timed session (see Perfusion_F.ino runCmd()/manualCmd()), but start()
        # above is called as soon as the GUI sends the command - before the
        # device has received and processed it. Samples that arrive in that
        # gap still carry the *previous* session's leftover elapsed_us == 0,
        # so skip them until a real (nonzero) elapsed_us shows the new session
        # has actually begun, then re-zero against that first real value so
        # the first row written is still 0.000 (relative spacing is untouched
        # since we're only subtracting a constant).
        samples = list(samples)
        voltages_v = list(voltages_v)
        elapsed_us = list(elapsed_us)
        now = time.monotonic()

        # Fallback: some setups (seen on macOS in manual-stimulus mode) never
        # send a running device clock - every elapsed_us is 0. If nothing but
        # zeros has arrived for over a second, stamp rows with the PC clock
        # instead (interpolated across each batch) so the CSV still has data.
        if not self._pc_mode and self._elapsed_offset_us is None:
            if any(e != 0 for e in elapsed_us):
                self._pending = []  # device clock is running: normal path below
            else:
                self._pending.append((now, samples, voltages_v))
                if now - self._started_at > 1.0:
                    self._pc_mode = True
                    pending, self._pending = self._pending, []
                    for t_batch, sm, vo in pending:
                        self._write_pc(t_batch, sm, vo)
                self._fh.flush()
                return
        if self._pc_mode:
            self._write_pc(now, samples, voltages_v)
            self._fh.flush()
            return

        for sample, voltage_v, elapsed in zip(samples, voltages_v, elapsed_us):
            if self._elapsed_offset_us is None:
                if elapsed == 0:
                    continue
                self._elapsed_offset_us = elapsed
            relative_elapsed = elapsed - self._elapsed_offset_us
            # elapsed_us only moves forward while the device's session is still
            # active (see analogInterrupt()); a drop means stopProtocol()/
            # MANUAL STIMULUS OFF already reset it to 0 on the device side
            # before our own stop() was called. Stop here instead of logging
            # a run of stale, offset-shifted (and often negative) rows while
            # waiting for that stop() to arrive.
            if (
                self._last_relative_elapsed_us is not None
                and relative_elapsed < self._last_relative_elapsed_us
            ):
                self._session_ended = True
                break
            self._last_relative_elapsed_us = relative_elapsed
            # voltage_v is already in volts (Perfusion_F.ino's analogInterrupt()
            # does the V/mA linear calibration directly), so no /1000 here.
            self._fh.write(f"{relative_elapsed / 1000.0:.3f},{sample},{voltage_v:.3f}\n")
        self._fh.flush()

    def _write_pc(self, now: float, samples: list, voltages_v: list) -> None:
        n = len(samples)
        if not n:
            return
        if self._pc_t0 is None:
            self._pc_t0 = now - 0.05  # one poll interval before the first batch
            self._pc_prev_t = self._pc_t0
        t_prev = self._pc_prev_t
        for i, (sample, voltage_v) in enumerate(zip(samples, voltages_v)):
            t = t_prev + (now - t_prev) * (i + 1) / n
            self._fh.write(f"{(t - self._pc_t0) * 1000.0:.3f},{sample},{voltage_v:.3f}\n")
        self._pc_prev_t = now

    def stop(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
