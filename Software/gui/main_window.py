from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QSpinBox,
    QWidget,
    QMenu,
)

from perfusion_app.models.protocol import ProtocolStep

from PySide6.QtCore import QPointF

class MainWindow(QMainWindow):
    refresh_ports_requested = Signal()
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    open_protocol_requested = Signal(str)
    save_protocol_requested = Signal(str)
    download_protocol_requested = Signal()
    run_protocol_requested = Signal()
    abort_protocol_requested = Signal()
    manual_stimulus_requested = Signal(str)
    closing = Signal()

    COLUMN_KEYS = [
        "DURATION_S",
        "PULSE",
        "WIDTH_MS",
        "FREQUENCY_HZ",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stimulation Control")
        self.resize(1200, 800)
        self._series = QLineSeries()
        self._voltage_series = QLineSeries()
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QGridLayout(central)

        self.port_combo = QComboBox()
        self.refresh_ports_button = QPushButton("Refresh Ports")
        self.connect_button = QPushButton("Connect")
        self.connection_label = QLabel("Disconnected")

        top_box = QGroupBox("Connection")
        top_layout = QHBoxLayout(top_box)
        top_layout.addWidget(QLabel("Port"))
        top_layout.addWidget(self.port_combo)
        top_layout.addWidget(self.refresh_ports_button)
        top_layout.addWidget(self.connect_button)
        top_layout.addWidget(self.connection_label)
        root.addWidget(top_box, 0, 0, 1, 2)

        self.protocol_table = QTableWidget(0, len(self.COLUMN_KEYS))
        self.protocol_table.setHorizontalHeaderLabels([
            "Duration (s)", "Pulse", "Width (ms)", "Freq (Hz)"
        ])
        self.protocol_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.protocol_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.protocol_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.protocol_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.protocol_table.customContextMenuRequested.connect(self._show_protocol_table_context_menu)

        protocol_box = QGroupBox("Stimulation Protocol Setup")
        protocol_layout = QVBoxLayout(protocol_box)
        buttons_row = QHBoxLayout()
        self.open_file_button = QPushButton("Open File")
        self.download_button = QPushButton("Download Protocol")
        self.run_button = QPushButton("Run Protocol")
        self.save_button = QPushButton("Save Protocol")
        self.download_button.setEnabled(False)
        self.run_button.setEnabled(False)
        buttons_row.addWidget(self.open_file_button)
        buttons_row.addWidget(self.download_button)
        buttons_row.addWidget(self.run_button)
        buttons_row.addWidget(self.save_button)
        protocol_layout.addLayout(buttons_row)
        protocol_layout.addWidget(self.protocol_table)
        root.addWidget(protocol_box, 1, 0)

        right_box = QVBoxLayout()
        manual_group = QGroupBox("Manual Control")
        manual_layout = QFormLayout(manual_group)
        self.stimulus_check = QCheckBox("Stimulus")
        self.frequency_input = QSpinBox()
        self.frequency_input.setRange(0, 500)
        self.frequency_input.setValue(20)
        self.frequency_input.setSuffix(" Hz")
        self.stimulus_status = QLabel("OFF")
        self.frequency_hint_label = QLabel("Enter frequency between 0 and 500 Hz")
        self.frequency_hint_label.setStyleSheet("color: blue;")
        manual_layout.addRow(self.frequency_hint_label)
        manual_layout.addRow("Frequency", self.frequency_input)
        manual_layout.addRow(self.stimulus_check, self.stimulus_status)
        right_box.addWidget(manual_group)

        self.debug_text = QPlainTextEdit()
        self.debug_text.setReadOnly(True)
        debug_group = QGroupBox("Debug")
        debug_layout = QVBoxLayout(debug_group)
        debug_layout.addWidget(self.debug_text)
        right_box.addWidget(debug_group)

        chart_group = QGroupBox("Current && Voltage")
        chart_layout = QVBoxLayout(chart_group)
        self._chart = QChart()
        self._chart.addSeries(self._series)
        self._chart.addSeries(self._voltage_series)
        self._series.setName("Current (mA)")
        self._voltage_series.setName("Voltage (V)")

        self._axis_x = QValueAxis()
        self._axis_x.setTitleText("Samples")
        self._axis_x.setRange(0, 100)

        self._axis_y = QValueAxis()
        self._axis_y.setTitleText("mA")
        self._axis_y.setRange(-100, 100)

        # Voltage gets its own axis on the right side of the same chart, so
        # both signals plot side by side against the same sample axis without
        # the mA range squashing the voltage trace. -50..50 is just the
        # initial placeholder before any data arrives (the expected input
        # range); update_plot() re-ranges it to the live min/max either way.
        self._axis_y2 = QValueAxis()
        self._axis_y2.setTitleText("V")
        self._axis_y2.setRange(-50, 50)

        self._chart.addAxis(self._axis_x, Qt.AlignBottom)
        self._chart.addAxis(self._axis_y, Qt.AlignLeft)
        self._chart.addAxis(self._axis_y2, Qt.AlignRight)

        self._series.attachAxis(self._axis_x)
        self._series.attachAxis(self._axis_y)
        self._voltage_series.attachAxis(self._axis_x)
        self._voltage_series.attachAxis(self._axis_y2)

        self._chart.legend().setVisible(True)
        self._chart_view = QChartView(self._chart)
        chart_layout.addWidget(self._chart_view)
        right_box.addWidget(chart_group)
        root.addLayout(right_box, 1, 1)

        self.version_label = QLabel("Migrated from PerfusionControl_2019_C")
        root.addWidget(self.version_label, 2, 0, 1, 2)

        self.refresh_ports_button.clicked.connect(self.refresh_ports_requested)
        self.connect_button.clicked.connect(self._handle_connect_clicked)
        self.open_file_button.clicked.connect(self._open_file)
        self.save_button.clicked.connect(self._save_file)
        self.download_button.clicked.connect(self.download_protocol_requested)
        self.run_button.clicked.connect(self._handle_run_clicked)
        self.stimulus_check.toggled.connect(self._emit_stimulus)

        self.delete_rows_shortcut = QShortcut(QKeySequence.Delete, self)
        self.delete_rows_shortcut.activated.connect(self._delete_selected_protocol_rows)
        
        self.duplicate_rows_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        self.duplicate_rows_shortcut.activated.connect(self._duplicate_selected_protocol_rows)
        
        self.insert_row_shortcut = QShortcut(QKeySequence(Qt.Key_Insert), self)
        self.insert_row_shortcut.activated.connect(self._insert_protocol_row_below_selection)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        self.menuBar().addAction(exit_action)
        # self.protocol_table.itemChanged.connect(self._on_protocol_table_item_changed)
        # self.ensure_trailing_empty_row()
        
    def _handle_connect_clicked(self) -> None:
        if self.connect_button.text() == "Connect":
            self.connect_requested.emit(self.port_combo.currentText())
        else:
            self.disconnect_requested.emit()

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open protocol", "", "Excel Files (*.xlsx *.xls)")
        if path:
            self.open_protocol_requested.emit(path)

    def _save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save protocol", "protocol.xlsx", "Excel Files (*.xlsx)")
        if path:
            if not path.lower().endswith('.xlsx'):
                path += '.xlsx'
            self.save_protocol_requested.emit(path)

    def _handle_run_clicked(self) -> None:
        if self.run_button.text() == "Run Protocol":
            self.run_protocol_requested.emit()
        else:
            self.abort_protocol_requested.emit()

    def _emit_stimulus(self, checked: bool) -> None:
        if not checked:
            self.manual_stimulus_requested.emit("Off")
            return

        freq = self.frequency_input.value()
        self.manual_stimulus_requested.emit(str(freq))

    def set_ports(self, ports: list[str]) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if current:
            idx = self.port_combo.findText(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def set_connected(self, connected: bool, port: str = "") -> None:
        self.connection_label.setText(
            f"Connected: {port}" if connected else "Disconnected")
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.download_button.setEnabled(
            connected and self.protocol_table.rowCount() > 0)

    def append_debug(self, text: str) -> None:
        self.debug_text.appendPlainText(text.rstrip())

    def clear_debug(self) -> None:
        self.debug_text.clear()


    # def _make_combo(self, options: list[str], value: str) -> QComboBox:
    #     combo = QComboBox()
    #     combo.addItems(options)
    #     idx = combo.findText(str(value), Qt.MatchFixedString)
    #     if idx >= 0:
    #         combo.setCurrentIndex(idx)
    #     return combo


    # def _set_table_text_cell(self, row: int, col: int, value) -> None:
    #     self.protocol_table.setItem(row, col, QTableWidgetItem(
    #         "" if value is None else str(value)))


    # def _set_table_combo_cell(self, row: int, col: int, options: list[str], value: str) -> None:
    #     combo = self._make_combo(options, "" if value is None else str(value))
    #     self.protocol_table.setCellWidget(row, col, combo)
    
    def set_protocol_steps(self, steps: list[ProtocolStep]) -> None:
        self.protocol_table.blockSignals(True)
        self.protocol_table.setRowCount(0)

        pulse_options = ["On", "Off"]

        for step in steps:
            row = self.protocol_table.rowCount()
            self.protocol_table.insertRow(row)

            self._set_table_text_cell(row, 0, step.duration_s)
            self._set_table_combo_cell(row, 1, pulse_options, "On" if step.pulse_on else "Off")
            self._set_table_text_cell(row, 2, step.pulse_width_ms)
            self._set_table_text_cell(row, 3, step.pulse_frequency_hz)

        # self.ensure_trailing_empty_row()
        self.protocol_table.blockSignals(False)
    
        self.download_button.setEnabled(self.connect_button.text() == "Disconnect" and bool(steps))
        self.run_button.setEnabled(bool(steps))

    def get_protocol_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        for row in range(self.protocol_table.rowCount()):
            row_data: dict[str, str] = {}

            for col, key in enumerate(self.COLUMN_KEYS):
                widget = self.protocol_table.cellWidget(row, col)
                if isinstance(widget, QComboBox):
                    row_data[key] = widget.currentText().strip()
                else:
                    item = self.protocol_table.item(row, col)
                    row_data[key] = item.text().strip() if item else ""

            rows.append(row_data)

        return rows
    
    
    def update_plot(self, samples: list[float], voltages_v: list[float]) -> None:
        if not samples:
            return

        #samples = samples[-600:]
        points = [QPointF(float(i), float(v)) for i, v in enumerate(samples)]
        self._series.replace(points)

        self._axis_x.setRange(0, max(1, len(samples) - 1))

        y_min = min(samples)
        y_max = max(samples)
        if y_min == y_max:
            y_min -= 1
            y_max += 1
        self._axis_y.setRange(y_min, y_max)

        if voltages_v:
            # already in volts (Perfusion_F.ino's analogInterrupt() does the
            # V/mA linear calibration directly, expected range -50V..+50V)
            vpoints = [QPointF(float(i), v) for i, v in enumerate(voltages_v)]
            self._voltage_series.replace(vpoints)

            v_min = min(voltages_v)
            v_max = max(voltages_v)
            if v_min == v_max:
                v_min -= 0.1
                v_max += 0.1
            self._axis_y2.setRange(v_min, v_max)
    
    def set_protocol_running(self, running: bool) -> None:
        self.run_button.setText(
            "Abort Protocol" if running else "Run Protocol")

    def set_stimulus_indicator(self, on: bool) -> None:
        self.stimulus_status.setText("ON" if on else "OFF")
        self.stimulus_status.setStyleSheet(f"color: {'green' if on else 'red'}")

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message: str) -> None:
        QMessageBox.information(self, "Info", message)
        
    def _make_combo(self, options: list[str], value: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(options)
        idx = combo.findText(str(value), Qt.MatchFixedString)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        # combo.currentIndexChanged.connect(lambda _=None: self.ensure_trailing_empty_row())
        return combo
    
    def _set_table_text_cell(self, row: int, col: int, value) -> None:
        self.protocol_table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
    
    def _set_table_combo_cell(self, row: int, col: int, options: list[str], value: str) -> None:
        combo = self._make_combo(options, "" if value is None else str(value))
        self.protocol_table.setCellWidget(row, col, combo)
    
    def add_empty_protocol_row(self):
        self.insert_empty_protocol_row(self.protocol_table.rowCount())
    
    def insert_empty_protocol_row(self, row: int) -> None:
        self.protocol_table.insertRow(row)

        pulse_options = ["On", "Off"]

        self._set_table_text_cell(row, 0, "")
        self._set_table_combo_cell(row, 1, pulse_options, "Off")
        self._set_table_text_cell(row, 2, "")
        self._set_table_text_cell(row, 3, "")

    def _row_is_blank(self, row: int):
        if row < 0 or row >= self.protocol_table.rowCount():
            return True

        for col in [0, 2, 3]:
            item = self.protocol_table.item(row, col)
            if item and item.text().strip():
                return False
        return True
    
    def ensure_trailing_empty_row(self):
        row_count = self.protocol_table.rowCount()
        if row_count == 0:
            self.add_empty_protocol_row()
            return
    
        if not self._row_is_blank(row_count - 1):
            self.add_empty_protocol_row()
    
    # def _on_protocol_table_item_changed(self, item: QTableWidgetItem):
        # self.ensure_trailing_empty_row()
    
    def _get_row_values(self, row: int) -> dict[str, str]:
        row_data: dict[str, str] = {}
    
        for col, key in enumerate(self.COLUMN_KEYS):
            widget = self.protocol_table.cellWidget(row, col)
            if isinstance(widget, QComboBox):
                row_data[key] = widget.currentText().strip()
            else:
                item = self.protocol_table.item(row, col)
                row_data[key] = item.text().strip() if item else ""
    
        return row_data
    
    def _populate_row_from_data(self, row: int, row_data: dict[str, str]) -> None:
        pulse_options = ["On", "Off"]

        self._set_table_text_cell(row, 0, row_data.get("DURATION_S", ""))
        self._set_table_combo_cell(row, 1, pulse_options, row_data.get("PULSE", "Off"))
        self._set_table_text_cell(row, 2, row_data.get("WIDTH_MS", ""))
        self._set_table_text_cell(row, 3, row_data.get("FREQUENCY_HZ", ""))
    
    def delete_protocol_rows(self, rows: list[int]) -> None:
        if not rows:
            return
    
        self.protocol_table.blockSignals(True)
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < self.protocol_table.rowCount():
                self.protocol_table.removeRow(row)
        self.protocol_table.blockSignals(False)
    
        # self.ensure_trailing_empty_row()
    
    def duplicate_protocol_rows(self, rows: list[int]) -> None:
        if not rows:
            return
    
        rows = sorted(set(rows))
        row_copies = [self._get_row_values(row) for row in rows]
    
        insert_at = rows[-1] + 1
    
        self.protocol_table.blockSignals(True)
        for offset, row_data in enumerate(row_copies):
            row = insert_at + offset
            self.protocol_table.insertRow(row)
            self._populate_row_from_data(row, row_data)
        self.protocol_table.blockSignals(False)
    
        self.clear_protocol_selection()
        for offset in range(len(row_copies)):
            self.protocol_table.selectRow(insert_at + offset)
    
        # self.ensure_trailing_empty_row()
    
    def clear_protocol_selection(self) -> None:
        self.protocol_table.clearSelection()
        
    def _show_protocol_table_context_menu(self, pos: QPoint) -> None:
        menu_row = self.protocol_table.rowAt(pos.y())
        selected_rows = sorted({index.row() for index in self.protocol_table.selectionModel().selectedRows()})
    
        menu = QMenu(self)
    
        add_action = QAction("Add Row Below", self)
        add_action.setShortcut("Insert")
        
        duplicate_action = QAction("Duplicate Selected Row(s)", self)
        duplicate_action.setShortcut("Ctrl+D")
        
        delete_action = QAction("Delete Selected Row(s)", self)
        delete_action.setShortcut("Delete")

        menu.addAction(add_action)
        menu.addAction(duplicate_action)
        menu.addAction(delete_action)

        chosen = menu.exec(self.protocol_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
    
        if chosen == add_action:
            if menu_row < 0:
                menu_row = self.protocol_table.rowCount() - 1
            self.protocol_table.blockSignals(True)
            self.insert_empty_protocol_row(menu_row + 1)
            self.protocol_table.blockSignals(False)
            # self.ensure_trailing_empty_row()
    
        elif chosen == duplicate_action:
            if not selected_rows:
                return
            self.duplicate_protocol_rows(selected_rows)
    
        elif chosen == delete_action:
            if not selected_rows:
                return
            self.delete_protocol_rows(selected_rows)  
            
    def _selected_protocol_rows(self) -> list[int]:
        return sorted({index.row() for index in self.protocol_table.selectionModel().selectedRows()})
    
    def _delete_selected_protocol_rows(self) -> None:
        rows = self._selected_protocol_rows()
        if not rows:
            return
        self.delete_protocol_rows(rows)
    
    def _duplicate_selected_protocol_rows(self) -> None:
        rows = self._selected_protocol_rows()
        if not rows:
            return
        self.duplicate_protocol_rows(rows)
    
    def _insert_protocol_row_below_selection(self) -> None:
        rows = self._selected_protocol_rows()
        if rows:
            insert_at = rows[-1] + 1
        else:
            current_row = self.protocol_table.currentRow()
            if current_row >= 0:
                insert_at = current_row + 1
            else:
                insert_at = self.protocol_table.rowCount()
    
        self.protocol_table.blockSignals(True)
        self.insert_empty_protocol_row(insert_at)
        self.protocol_table.blockSignals(False)
        # self.ensure_trailing_empty_row()
        
    def closeEvent(self, event) -> None:
        self.closing.emit()
        super().closeEvent(event)        
            