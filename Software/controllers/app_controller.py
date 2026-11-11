from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, QMetaObject, Qt

from perfusion_app.gui.main_window import MainWindow
from perfusion_app.models.device_state import DeviceState
from perfusion_app.models.protocol import ProtocolStep
from perfusion_app.serial_comm.protocol_codec import ProtocolCodec
from perfusion_app.serial_comm.serial_worker import SerialWorker
from perfusion_app.services.logging_service import CsvLogger
from perfusion_app.services.protocol_io import ProtocolFileError, load_protocol_from_excel, save_protocol_to_excel


def _app_base_dir() -> Path:
    # Where "Data" (and the user's own "Protocols") should live: right next
    # to the packaged app, so it's easy to find regardless of platform.
    #
    # When run from source, the current working directory is a reasonable
    # default (whoever launches `python -m perfusion_app.main` is presumably
    # sitting in the project folder already).
    #
    # When frozen by PyInstaller, Path.cwd() is NOT reliable: double-clicking
    # Stimulation Control.exe from Windows Explorer does set cwd to the exe's
    # own folder, but double-clicking Stimulation Control.app from macOS
    # Finder does NOT set cwd to anywhere inside the bundle - it's typically
    # the user's home directory - which would silently put "Data" somewhere
    # the user doesn't expect to find it. Anchor to sys.executable instead,
    # and for a macOS .app, walk up out of Contents/MacOS/ to the folder that
    # *contains* the .app (its sibling), not somewhere inside the bundle.
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        if sys.platform == "darwin" and "Contents/MacOS" in str(exe_path):
            return exe_path.parents[3]
        return exe_path.parent
    return Path.cwd()


class AppController:
    def __init__(self) -> None:
        self.window = MainWindow()
        self.state = DeviceState()
        self.steps: list[ProtocolStep] = []
        self.protocol_name = ""
        self.logger = CsvLogger(_app_base_dir() / "Data")

        self._thread = QThread()
        self.worker = SerialWorker()
        self.worker.moveToThread(self._thread)
        self._thread.start()

        self._wire_ui()
        self._wire_worker()
        self.window.destroyed.connect(self.shutdown)        
        self.window.refresh_ports_requested.emit()
        self._last_plot_time = 0.0

    def _wire_ui(self) -> None:
        self.window.refresh_ports_requested.connect(self.worker.refresh_ports)
        self.window.connect_requested.connect(self.worker.connect_port)
        self.window.disconnect_requested.connect(self.worker.disconnect_port)
        self.window.open_protocol_requested.connect(self._open_protocol)
        self.window.save_protocol_requested.connect(self._save_protocol)
        self.window.download_protocol_requested.connect(self._download_protocol)
        self.window.run_protocol_requested.connect(self._run_protocol)
        self.window.abort_protocol_requested.connect(self._abort_protocol)
        self.window.manual_stimulus_requested.connect(self._manual_stimulus)
        self.window.closing.connect(self.shutdown)

    def _wire_worker(self) -> None:
        self.worker.ports_updated.connect(self.window.set_ports)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.error.connect(self.window.show_error)
        #self.worker.text_received.connect(self.window.append_debug)
        self.worker.samples_received.connect(self._on_samples)
        self.worker.protocol_done.connect(self._on_protocol_done)

    def show(self) -> None:
        self.window.show()

    def _on_connected(self, port: str) -> None:
        self.state.connected = True
        self.state.port_name = port
        self.window.set_connected(True, port)
        self.window.append_debug(f"Connected to {port}")

    def _on_disconnected(self) -> None:
        self.state.connected = False
        self.state.port_name = ""
        self.window.set_connected(False)

    def _open_protocol(self, path: str) -> None:
        try:
            self.steps = load_protocol_from_excel(path)
        except ProtocolFileError as exc:
            self.window.show_error(str(exc))
            return
        self.protocol_name = Path(path).stem
        self.window.set_protocol_steps(self.steps)
        self.window.append_debug(f"Loaded protocol: {path}")
        for line in ProtocolCodec.encode_protocol_download(self.steps):
            self.window.append_debug(f"PREVIEW >>> {line}")

    def _save_protocol(self, path: str) -> None:
        try:
            steps = self._steps_from_table()
            save_protocol_to_excel(path, steps)
        except Exception as exc:
            self.window.show_error(str(exc))
            return
        self.protocol_name = Path(path).stem
        self.window.show_info(f"Saved protocol to {path}")

    def _steps_from_table(self) -> list[ProtocolStep]:
        steps: list[ProtocolStep] = []
        for row_number, row in enumerate(self.window.get_protocol_rows(), start=1):
            if not row["DURATION_S"]:
                continue
            pulse_on = (row["PULSE"] or "").strip().lower() == "on"
            width = float(row["WIDTH_MS"]) if row["WIDTH_MS"] else 0.0
            frequency = float(row["FREQUENCY_HZ"]) if row["FREQUENCY_HZ"] else 0.0
            try:
                steps.append(
                    ProtocolStep(
                        duration_s=float(row["DURATION_S"]),
                        pulse_on=pulse_on,
                        pulse_width_ms=width,
                        pulse_frequency_hz=frequency,
                    )
                )
            except ValueError as exc:
                raise ValueError(f"Invalid numeric value on table row {row_number}: {exc}") from exc
        return steps

    def _download_protocol(self) -> None:
        try:
            self.steps = self._steps_from_table()
        except Exception as exc:
            self.window.show_error(str(exc))
            return
        self.window.clear_debug()
        for line in ProtocolCodec.encode_protocol_download(self.steps):
            self.worker.send_line(line)
            self.window.append_debug(f">>> {line}")
        self.window.set_protocol_running(False)
        self.window.run_button.setEnabled(True)

    def _run_protocol(self) -> None:
        self.logger.start(self.protocol_name)
        self.state.protocol_running = True
        self.window.set_protocol_running(True)
        self.worker.send_line("RUN")
        self.window.append_debug(">>> RUN")

    def _abort_protocol(self) -> None:
        self.state.protocol_running = False
        self.window.set_protocol_running(False)
        self.worker.send_line("STOP")
        self.window.append_debug(">>> STOP")
        self.logger.stop()

    def _manual_stimulus(self, mode: str) -> None:
        cmd = ProtocolCodec.manual_stimulus_command(mode)
        self.worker.send_line(cmd)
        self.window.set_stimulus_indicator(mode != "Off")
        self.window.append_debug(f">>> {cmd}")

        if mode == "Off":
            self.logger.stop()
        else:
            self.logger.start(f"{mode}Hz")

    def _on_samples(self, samples: list[float], voltages_v: list[float], elapsed_us: list[int]) -> None:
        self.state.recent_samples = samples
        self.state.recent_voltages_v = voltages_v
        self.state.recent_elapsed_us = elapsed_us

        #now = time.time()
        #if now - self._last_plot_time >= 0.1:   # 10 Hz
            #self._last_plot_time = now
        self.window.update_plot(samples, voltages_v)

        if self.logger.is_active:
            self.logger.write_samples(samples, voltages_v, elapsed_us)

    def _on_protocol_done(self) -> None:
        self.state.protocol_running = False
        self.window.set_protocol_running(False)
        self.logger.stop()
        self.window.append_debug(">>> DONE")

    def shutdown(self) -> None:
        self.state.protocol_running = False
    
        try:
            self.logger.stop()
        except Exception:
            pass
    
        try:
            QMetaObject.invokeMethod(self.worker, "disconnect_port", Qt.BlockingQueuedConnection)
        except Exception:
            pass
    
        self._thread.quit()
        self._thread.wait(2000)