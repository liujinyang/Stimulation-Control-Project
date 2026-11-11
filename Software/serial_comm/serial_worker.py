from __future__ import annotations

import time

import serial
from serial.tools import list_ports
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from perfusion_app.serial_comm.protocol_codec import ProtocolCodec


class SerialWorker(QObject):
    connected = Signal(str)
    disconnected = Signal()
    error = Signal(str)
    text_received = Signal(str)
    samples_received = Signal(list, list, list)
    protocol_done = Signal()
    ports_updated = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self._serial: serial.Serial | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5)  # read often so the OS serial buffer never overflows
        self._poll_timer.timeout.connect(self._poll_serial)
        self._rxbuf = ""
        self._last_emit = 0.0
        self._acc_c: list[float] = []
        self._acc_v: list[float] = []
        self._acc_e: list[int] = []
        self._done_pending = False

    @Slot()
    def refresh_ports(self) -> None:
        ports = [p.device for p in list_ports.comports()]
        self.ports_updated.emit(ports)

    @Slot(str, int)
    def connect_port(self, port: str, baudrate: int = 115200) -> None:
        try:
            self.disconnect_port()
            self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=0.05)
            self._poll_timer.start()
            self.connected.emit(port)
        except Exception as exc:
            self.error.emit(str(exc))

    @Slot()
    def disconnect_port(self) -> None:
        self._poll_timer.stop()
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None
        self.disconnected.emit()

    @Slot(str)
    def send_line(self, text: str) -> None:
        if not self._serial or not self._serial.is_open:
            self.error.emit("Serial port is not connected")
            return
        try:
            self._serial.write((text + "\r\n").encode("ascii", errors="replace"))
        except Exception as exc:
            self.error.emit(str(exc))

    @Slot()
    def _poll_serial(self) -> None:
        if not self._serial or not self._serial.is_open:
            return
        try:
            waiting = self._serial.in_waiting
            if waiting <= 0:
                return
            raw = self._serial.read(waiting).decode("ascii", errors="replace")
            self.text_received.emit(raw)
            c, v, e, done, self._rxbuf = ProtocolCodec.parse_buffered(self._rxbuf + raw)
            self._acc_c += c
            self._acc_v += v
            self._acc_e += e
            self._done_pending = self._done_pending or done
            # Read at 5 ms but only hand data to the GUI about every 50 ms,
            # so plotting/logging load stays what it was.
            now = time.monotonic()
            if now - self._last_emit >= 0.05 or self._done_pending:
                self._last_emit = now
                if self._acc_c:
                    self.samples_received.emit(self._acc_c, self._acc_v, self._acc_e)
                    self._acc_c, self._acc_v, self._acc_e = [], [], []
                if self._done_pending:
                    self._done_pending = False
                    self._rxbuf = ""
                    self.protocol_done.emit()
        except Exception as exc:
            self.error.emit(str(exc))
