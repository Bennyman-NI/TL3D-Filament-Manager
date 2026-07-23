from __future__ import annotations

import argparse
import sys
import threading

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

import identify_tag
import memory_inspector
from rfid_monitor import (
    WAITING_STATUS,
    IdentifierDisplayState,
    ReaderConnection,
    RfidMonitor,
    TagReadContext,
)


class QtRfidMonitorSignals(QObject):
    readerConnectionChanged = Signal(object)
    tagDetected = Signal(object)
    tagRemoved = Signal(str)
    tagAvailable = Signal(object)
    monitorError = Signal(str)
    finished = Signal(int)


class QtDumpSignals(QObject):
    dumpStarted = Signal()
    dumpFinished = Signal(object)
    dumpError = Signal(str)


class QtRfidMonitorWorker(QObject):
    def __init__(self, monitor: RfidMonitor) -> None:
        super().__init__()
        self.monitor = monitor
        self.stop_event = threading.Event()
        self.signals = QtRfidMonitorSignals()

    def run(self) -> None:
        exit_code = self.monitor.run(QtRfidMonitorCallbacks(self.signals), self.stop_event)
        self.signals.finished.emit(exit_code)

    def stop(self) -> None:
        self.stop_event.set()


class QtDumpWorker(QObject):
    def __init__(self, context: TagReadContext) -> None:
        super().__init__()
        self.context = context
        self.signals = QtDumpSignals()

    def run(self) -> None:
        self.signals.dumpStarted.emit()
        try:
            dump = memory_inspector.BambuMemoryInspector().inspect_card(
                self.context.card,
                self.context.pcsc,
                self.context.identity,
            )
        except Exception as exc:
            self.signals.dumpError.emit(str(exc))
            return
        self.signals.dumpFinished.emit(dump)


class QtRfidMonitorCallbacks:
    def __init__(self, signals: QtRfidMonitorSignals) -> None:
        self.signals = signals

    def reader_connection_changed(self, connection: ReaderConnection) -> None:
        self.signals.readerConnectionChanged.emit(connection)

    def tag_detected(self, identity: identify_tag.TagIdentity) -> None:
        self.signals.tagDetected.emit(identity)

    def tag_removed(self, reader_name: str) -> None:
        self.signals.tagRemoved.emit(reader_name)

    def tag_available(self, context: TagReadContext) -> None:
        self.signals.tagAvailable.emit(context)

    def monitor_error(self, message: str) -> None:
        self.signals.monitorError.emit(message)


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        reader_name: str = identify_tag.DEFAULT_READER_NAME,
        any_reader: bool = False,
    ) -> None:
        super().__init__()
        self.reader_name = reader_name
        self.any_reader = any_reader
        self.thread: QThread | None = None
        self.worker: QtRfidMonitorWorker | None = None
        self.dump_thread: QThread | None = None
        self.dump_worker: QtDumpWorker | None = None
        self.display_state = IdentifierDisplayState()
        self.last_tag_context: TagReadContext | None = None
        self.last_memory_dump: memory_inspector.RawDump | None = None

        self.setWindowTitle("Bambu RFID Identifier")
        self.resize(980, 640)

        title = QLabel("Bambu RFID Identifier")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: 600;")

        self.connection_label = QLabel("Starting")
        self.reader_label = QLabel("Unknown")
        self.status_label = QLabel(WAITING_STATUS)
        self.uid_label = QLabel("")
        self.atr_label = QLabel("")
        self.memory_label = QLabel("")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #9f1239;")

        for label in (
            self.connection_label,
            self.reader_label,
            self.status_label,
            self.uid_label,
            self.atr_label,
            self.memory_label,
        ):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Reader connection status", self.connection_label)
        form.addRow("Reader name", self.reader_label)
        form.addRow("Current status", self.status_label)
        form.addRow("UID", self.uid_label)
        form.addRow("ATR", self.atr_label)
        form.addRow("Memory inspection", self.memory_label)

        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setLayout(form)

        self.memory_table = QTableWidget(0, 5)
        self.memory_table.setHorizontalHeaderLabels(["Sector", "Block", "Absolute", "Status", "Hex data / message"])
        self.memory_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.memory_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self.restart_button = QPushButton("Restart reader monitor")
        self.restart_button.clicked.connect(self.restart_monitor)
        self.read_button = QPushButton("Read Bambu Tag")
        self.read_button.setEnabled(False)
        self.read_button.clicked.connect(self.start_dump)
        self.save_button = QPushButton("Save raw dump")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_raw_dump)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.restart_button)
        button_layout.addWidget(self.read_button)
        button_layout.addWidget(self.save_button)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(frame)
        layout.addWidget(self.error_label)
        layout.addWidget(self.memory_table)
        layout.addLayout(button_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.start_monitor()

    def start_monitor(self) -> None:
        self.stop_monitor()
        self.display_state.reset_for_monitor_start()
        self.refresh_display()

        try:
            pcsc = identify_tag.load_pcsc_api()
        except RuntimeError as exc:
            self.apply_reader_connection(ReaderConnection(False, "", str(exc)))
            return

        self.thread = QThread()
        self.worker = QtRfidMonitorWorker(
            RfidMonitor(
                pcsc,
                reader_name=self.reader_name,
                any_reader=self.any_reader,
            )
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.signals.readerConnectionChanged.connect(self.apply_reader_connection)
        self.worker.signals.tagDetected.connect(self.apply_tag_detected)
        self.worker.signals.tagRemoved.connect(self.apply_tag_removed)
        self.worker.signals.tagAvailable.connect(self.remember_tag_context)
        self.worker.signals.monitorError.connect(self.apply_monitor_error)
        self.worker.signals.finished.connect(self.thread.quit)
        self.worker.signals.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.clear_thread_references)
        self.thread.start()

    def restart_monitor(self) -> None:
        self.start_monitor()

    def stop_monitor(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(1000)

    def clear_thread_references(self) -> None:
        self.thread = None
        self.worker = None

    def apply_reader_connection(self, connection: ReaderConnection) -> None:
        self.display_state.apply_reader_connection(connection)
        if not connection.connected:
            self.clear_memory_table()
            self.last_tag_context = None
            self.read_button.setEnabled(False)
        self.refresh_display()

    def apply_tag_detected(self, identity: identify_tag.TagIdentity) -> None:
        self.display_state.apply_tag_detected(identity)
        if identity.uid is not None:
            self.clear_memory_table()
            self.read_button.setEnabled(self.last_tag_context is not None)
        self.refresh_display()

    def apply_tag_removed(self, reader_name: str) -> None:
        self.display_state.apply_tag_removed(reader_name)
        self.last_tag_context = None
        self.read_button.setEnabled(False)
        self.refresh_display()

    def apply_monitor_error(self, message: str) -> None:
        self.display_state.apply_monitor_error(message)
        self.refresh_display()

    def remember_tag_context(self, context: TagReadContext) -> None:
        self.last_tag_context = context
        self.read_button.setEnabled(True)

    def start_dump(self) -> None:
        if self.last_tag_context is None or self.dump_thread is not None:
            return

        self.display_state.apply_dump_started()
        self.read_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.refresh_display()

        self.dump_thread = QThread()
        self.dump_worker = QtDumpWorker(self.last_tag_context)
        self.dump_worker.moveToThread(self.dump_thread)
        self.dump_thread.started.connect(self.dump_worker.run)
        self.dump_worker.signals.dumpFinished.connect(self.apply_memory_dump)
        self.dump_worker.signals.dumpError.connect(self.apply_dump_error)
        self.dump_worker.signals.dumpFinished.connect(self.dump_thread.quit)
        self.dump_worker.signals.dumpError.connect(self.dump_thread.quit)
        self.dump_thread.finished.connect(self.dump_worker.deleteLater)
        self.dump_thread.finished.connect(self.dump_thread.deleteLater)
        self.dump_thread.finished.connect(self.clear_dump_thread_references)
        self.dump_thread.start()

    def clear_dump_thread_references(self) -> None:
        self.dump_thread = None
        self.dump_worker = None
        self.read_button.setEnabled(self.last_tag_context is not None)

    def apply_memory_dump(self, dump: memory_inspector.RawDump) -> None:
        self.last_memory_dump = dump
        self.display_state.apply_memory_dump(dump)
        self.populate_memory_table(dump)
        self.save_button.setEnabled(True)
        self.refresh_display()

    def apply_dump_error(self, message: str) -> None:
        self.display_state.memory_summary = "Memory read failed"
        self.display_state.error = message
        self.refresh_display()

    def populate_memory_table(self, dump: memory_inspector.RawDump) -> None:
        rows = [(sector, block) for sector in dump.sectors for block in sector.blocks]
        self.memory_table.setRowCount(len(rows))
        for row, (sector, block) in enumerate(rows):
            detail = block.data_hex or block.error or sector.error or ""
            values = [str(sector.sector), str(block.block), str(block.absolute_block), block.status, detail]
            for column, value in enumerate(values):
                self.memory_table.setItem(row, column, QTableWidgetItem(value))
        self.memory_table.resizeColumnsToContents()

    def clear_memory_table(self) -> None:
        self.last_memory_dump = None
        self.memory_table.setRowCount(0)
        self.save_button.setEnabled(False)

    def save_raw_dump(self) -> None:
        if self.last_memory_dump is None:
            return

        directory = QFileDialog.getExistingDirectory(self, "Choose RFID dump folder")
        if not directory:
            return

        path = memory_inspector.save_memory_dump(self.last_memory_dump, directory)
        self.display_state.memory_summary = f"Saved raw dump: {path}"
        self.refresh_display()

    def refresh_display(self) -> None:
        self.connection_label.setText(self.display_state.connection_status)
        self.reader_label.setText(self.display_state.reader_name)
        self.status_label.setText(self.display_state.current_status)
        self.uid_label.setText(self.display_state.uid)
        self.atr_label.setText(self.display_state.atr)
        self.memory_label.setText(self.display_state.memory_summary)
        self.error_label.setText(self.display_state.error)

    def closeEvent(self, event: object) -> None:
        self.stop_monitor()
        if self.dump_thread is not None and self.dump_thread.isRunning():
            self.dump_thread.quit()
            self.dump_thread.wait(3000)
        super().closeEvent(event)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone read-only PySide6 GUI for TL3D Bambu RFID identification."
    )
    parser.add_argument(
        "--reader-name",
        default=identify_tag.DEFAULT_READER_NAME,
        help=f"Reader name substring to select. Default: {identify_tag.DEFAULT_READER_NAME}",
    )
    parser.add_argument(
        "--any-reader",
        action="store_true",
        help="Use the first PC/SC reader instead of requiring an ACR1255U-J1 match.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    window = MainWindow(reader_name=args.reader_name, any_reader=args.any_reader)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
