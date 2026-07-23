from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Protocol

import identify_tag
import memory_inspector


WAITING_STATUS = "Waiting"
TAG_DETECTED_STATUS = "Tag detected"
TAG_REMOVED_STATUS = "Tag removed"


@dataclass(frozen=True)
class ReaderConnection:
    connected: bool
    reader_name: str
    message: str


@dataclass(frozen=True)
class TagReadContext:
    card: object
    pcsc: identify_tag.PcscApi
    identity: identify_tag.TagIdentity


@dataclass
class IdentifierDisplayState:
    connection_status: str = "Starting"
    reader_name: str = "Unknown"
    current_status: str = WAITING_STATUS
    uid: str = ""
    atr: str = ""
    error: str = ""
    memory_summary: str = ""

    def reset_for_monitor_start(self) -> None:
        self.connection_status = "Starting"
        self.reader_name = "Unknown"
        self.current_status = WAITING_STATUS
        self.clear_identity()
        self.memory_summary = ""
        self.error = ""

    def apply_reader_connection(self, connection: ReaderConnection) -> None:
        self.connection_status = connection.message
        self.reader_name = connection.reader_name or "Unavailable"
        if not connection.connected:
            self.current_status = WAITING_STATUS
            self.clear_identity()
            self.memory_summary = ""
            self.error = connection.message

    def apply_tag_detected(self, identity: identify_tag.TagIdentity) -> None:
        self.current_status = TAG_DETECTED_STATUS
        self.reader_name = identity.reader_name
        if identity.uid is not None:
            self.clear_identity()
            self.uid = identity.uid
            self.atr = identity.atr or "Unavailable"
            self.memory_summary = "Ready to read Bambu tag."
            self.error = ""
            return

        self.error = identity.uid_error or ""

    def apply_tag_removed(self, reader_name: str) -> None:
        self.current_status = TAG_REMOVED_STATUS
        self.reader_name = reader_name
        self.error = ""

    def apply_monitor_error(self, message: str) -> None:
        self.connection_status = "Error"
        self.error = message

    def apply_dump_started(self) -> None:
        self.memory_summary = "Reading Bambu tag..."

    def apply_memory_dump(self, dump: memory_inspector.RawDump) -> None:
        blocks = [block for sector in dump.sectors for block in sector.blocks]
        total_blocks = len(blocks)
        readable_blocks = sum(1 for block in blocks if block.status in {"success", "read_warning"})
        failed_blocks = total_blocks - readable_blocks
        if total_blocks == 0:
            self.memory_summary = f"Memory read: {dump.status}"
            return

        self.memory_summary = f"Memory read: {readable_blocks}/{total_blocks} blocks readable"
        if failed_blocks:
            self.memory_summary += f", {failed_blocks} failed"

    def clear_identity(self) -> None:
        self.uid = ""
        self.atr = ""


class RfidMonitorCallbacks(Protocol):
    def reader_connection_changed(self, connection: ReaderConnection) -> None:
        ...

    def tag_detected(self, identity: identify_tag.TagIdentity) -> None:
        ...

    def tag_removed(self, reader_name: str) -> None:
        ...

    def monitor_error(self, message: str) -> None:
        ...

    def tag_available(self, context: TagReadContext) -> None:
        ...

    def memory_dumped(self, dump: memory_inspector.RawDump) -> None:
        ...


class RfidMonitor:
    def __init__(
        self,
        pcsc: identify_tag.PcscApi,
        *,
        reader_name: str = identify_tag.DEFAULT_READER_NAME,
        any_reader: bool = False,
        event_timeout_seconds: float = 0.2,
    ) -> None:
        self.pcsc = pcsc
        self.reader_name = reader_name
        self.any_reader = any_reader
        self.event_timeout_seconds = event_timeout_seconds

    def run(self, callbacks: RfidMonitorCallbacks, stop_event: threading.Event) -> int:
        available_readers = identify_tag.list_pcsc_readers(self.pcsc)
        try:
            selected_reader = identify_tag.select_reader(
                available_readers,
                reader_name=self.reader_name,
                any_reader=self.any_reader,
            )
        except RuntimeError as exc:
            callbacks.reader_connection_changed(ReaderConnection(False, "", str(exc)))
            return 2

        selected_reader_name = str(selected_reader)
        callbacks.reader_connection_changed(
            ReaderConnection(True, selected_reader_name, "Connected")
        )

        try:
            card_monitor = self.pcsc.card_monitor()
        except Exception as exc:
            callbacks.monitor_error(f"Could not start PC/SC card monitor: {exc}")
            return 3

        events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        observer = identify_tag.CardEventObserver(events)
        last_present_key: tuple[str, str | None, str] | None = None
        observer_added = False

        try:
            card_monitor.addObserver(observer)
            observer_added = True

            while not stop_event.is_set():
                try:
                    event_type, card = events.get(timeout=self.event_timeout_seconds)
                except queue.Empty:
                    continue

                card_reader_name = str(getattr(card, "reader", ""))
                if card_reader_name != selected_reader_name:
                    continue

                if event_type == "removed":
                    last_present_key = None
                    callbacks.tag_removed(card_reader_name)
                    continue

                identity = identify_tag.identify_card(card, self.pcsc)
                if identity.repeat_key == last_present_key:
                    continue

                callbacks.tag_detected(identity)
                if identity.uid is not None:
                    callbacks.tag_available(TagReadContext(card=card, pcsc=self.pcsc, identity=identity))
                last_present_key = identity.repeat_key
        except Exception as exc:
            callbacks.monitor_error(f"PC/SC monitor error: {exc}")
            return 3
        finally:
            if observer_added:
                card_monitor.deleteObserver(observer)

        return 0
