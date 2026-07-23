from __future__ import annotations

import threading
import unittest

import identify_tag
import memory_inspector
import rfid_monitor


class FakePcscException(Exception):
    pass


class FakeCardConnection:
    T1_protocol = object()


class FakeConnection:
    def __init__(self, *, data=None, status=(0x90, 0x00)) -> None:
        self.data = [] if data is None else data
        self.status = status
        self.last_apdu = None

    def connect(self, protocol=None) -> None:
        return

    def transmit(self, apdu):
        self.last_apdu = apdu
        sw1, sw2 = self.status
        return self.data, sw1, sw2

    def disconnect(self) -> None:
        return


class FakeCard:
    def __init__(self, connection: FakeConnection, *, reader="ACS ACR1255U-J1 00 00") -> None:
        self.reader = reader
        self.atr = [0x3B, 0x8F, 0x80, 0x01]
        self.connection = connection

    def createConnection(self) -> FakeConnection:
        return self.connection


class FakeCardMonitor:
    def __init__(self, added_cards=None, removed_cards=None) -> None:
        self.added_cards = [] if added_cards is None else added_cards
        self.removed_cards = [] if removed_cards is None else removed_cards
        self.deleted_observer = None

    def addObserver(self, observer) -> None:
        observer.update(self, (self.added_cards, self.removed_cards))

    def deleteObserver(self, observer) -> None:
        self.deleted_observer = observer


class RecordingCallbacks:
    def __init__(self, stop_event: threading.Event | None = None, *, stop_on_tag_available: bool = False) -> None:
        self.stop_event = stop_event
        self.stop_on_tag_available = stop_on_tag_available
        self.reader_connections: list[rfid_monitor.ReaderConnection] = []
        self.detected: list[identify_tag.TagIdentity] = []
        self.removed: list[str] = []
        self.errors: list[str] = []
        self.tag_contexts: list[rfid_monitor.TagReadContext] = []

    def reader_connection_changed(self, connection: rfid_monitor.ReaderConnection) -> None:
        self.reader_connections.append(connection)

    def tag_detected(self, identity: identify_tag.TagIdentity) -> None:
        self.detected.append(identity)

    def tag_removed(self, reader_name: str) -> None:
        self.removed.append(reader_name)
        if self.stop_event is not None:
            self.stop_event.set()

    def monitor_error(self, message: str) -> None:
        self.errors.append(message)
        if self.stop_event is not None:
            self.stop_event.set()

    def tag_available(self, context: rfid_monitor.TagReadContext) -> None:
        self.tag_contexts.append(context)
        if self.stop_event is not None and self.stop_on_tag_available:
            self.stop_event.set()

    def memory_dumped(self, dump: memory_inspector.RawDump) -> None:
        return


def make_pcsc(*, readers, monitor) -> identify_tag.PcscApi:
    return identify_tag.PcscApi(
        card_connection=FakeCardConnection,
        card_monitor=lambda: monitor,
        card_connection_exception=FakePcscException,
        no_card_exception=FakePcscException,
        no_readers_exception=FakePcscException,
        readers=lambda: readers,
    )


class RfidGuiMonitorTests(unittest.TestCase):
    def test_display_state_keeps_last_successful_uid_and_atr_after_removal(self) -> None:
        state = rfid_monitor.IdentifierDisplayState()

        state.apply_tag_detected(
            identify_tag.TagIdentity(
                reader_name="ACS ACR1255U-J1 00 00",
                atr="3B8F8001",
                uid="04123456",
            )
        )
        state.apply_tag_removed("ACS ACR1255U-J1 00 00")

        self.assertEqual(state.current_status, rfid_monitor.TAG_REMOVED_STATUS)
        self.assertEqual(state.reader_name, "ACS ACR1255U-J1 00 00")
        self.assertEqual(state.uid, "04123456")
        self.assertEqual(state.atr, "3B8F8001")

    def test_display_state_clears_uid_and_atr_when_monitor_restarts(self) -> None:
        state = rfid_monitor.IdentifierDisplayState(uid="04123456", atr="3B8F8001")

        state.reset_for_monitor_start()

        self.assertEqual(state.current_status, rfid_monitor.WAITING_STATUS)
        self.assertEqual(state.uid, "")
        self.assertEqual(state.atr, "")

    def test_display_state_clears_uid_and_atr_when_reader_disconnects(self) -> None:
        state = rfid_monitor.IdentifierDisplayState(uid="04123456", atr="3B8F8001")

        state.apply_reader_connection(
            rfid_monitor.ReaderConnection(
                connected=False,
                reader_name="",
                message="No PC/SC readers were found.",
            )
        )

        self.assertEqual(state.current_status, rfid_monitor.WAITING_STATUS)
        self.assertEqual(state.uid, "")
        self.assertEqual(state.atr, "")
        self.assertEqual(state.error, "No PC/SC readers were found.")

    def test_display_state_keeps_last_successful_uid_and_atr_after_failed_read(self) -> None:
        state = rfid_monitor.IdentifierDisplayState(uid="04123456", atr="3B8F8001")

        state.apply_tag_detected(
            identify_tag.TagIdentity(
                reader_name="ACS ACR1255U-J1 00 00",
                atr="3B000000",
                uid=None,
                uid_error="UID command unsupported or rejected. Status: 6A 81",
            )
        )

        self.assertEqual(state.current_status, rfid_monitor.TAG_DETECTED_STATUS)
        self.assertEqual(state.uid, "04123456")
        self.assertEqual(state.atr, "3B8F8001")
        self.assertIn("UID command unsupported", state.error)

    def test_display_state_replaces_uid_and_atr_on_next_successful_read(self) -> None:
        state = rfid_monitor.IdentifierDisplayState(uid="04123456", atr="3B8F8001")

        state.apply_tag_detected(
            identify_tag.TagIdentity(
                reader_name="ACS ACR1255U-J1 00 00",
                atr="3B8F9002",
                uid="04ABCDEF",
            )
        )

        self.assertEqual(state.current_status, rfid_monitor.TAG_DETECTED_STATUS)
        self.assertEqual(state.uid, "04ABCDEF")
        self.assertEqual(state.atr, "3B8F9002")
        self.assertEqual(state.error, "")

    def test_display_state_summarizes_memory_dump_failures(self) -> None:
        state = rfid_monitor.IdentifierDisplayState()
        dump = memory_inspector.RawDump(
            schema_version=1,
            created_at="2026-07-23T12:00:00+00:00",
            reader_name="reader",
            uid="04123456",
            atr="3B8F8001",
            tag_type="MIFARE Classic 1K",
            upstream_reference=memory_inspector.upstream_reference(),
            sectors=[
                memory_inspector.SectorDump(
                    sector=0,
                    authentication_status="success",
                    blocks=[
                        memory_inspector.BlockDump(block=0, absolute_block=0, status="success", data_hex="00" * 16),
                        memory_inspector.BlockDump(block=1, absolute_block=1, status="read_failed", error="Status: 6A 82"),
                    ],
                )
            ],
            status="partial",
            error=None,
            software={"tool": memory_inspector.TOOL_VERSION},
        )

        state.apply_memory_dump(dump)

        self.assertEqual(state.memory_summary, "Memory read: 1/2 blocks readable, 1 failed")

    def test_monitor_reports_missing_reader_without_starting_card_monitor(self) -> None:
        stop_event = threading.Event()
        callbacks = RecordingCallbacks(stop_event)
        monitor = rfid_monitor.RfidMonitor(make_pcsc(readers=[], monitor=FakeCardMonitor()))

        exit_code = monitor.run(callbacks, stop_event)

        self.assertEqual(exit_code, 2)
        self.assertFalse(callbacks.reader_connections[0].connected)
        self.assertIn("No PC/SC readers", callbacks.reader_connections[0].message)

    def test_monitor_emits_detection_and_removal_using_existing_read_logic(self) -> None:
        stop_event = threading.Event()
        callbacks = RecordingCallbacks(stop_event)
        connection = FakeConnection(data=[0x04, 0x12, 0x34, 0x56])
        card = FakeCard(connection)
        card_monitor = FakeCardMonitor(added_cards=[card], removed_cards=[card])
        pcsc = make_pcsc(readers=["ACS ACR1255U-J1 00 00"], monitor=card_monitor)

        exit_code = rfid_monitor.RfidMonitor(pcsc, event_timeout_seconds=0.01).run(callbacks, stop_event)

        self.assertEqual(exit_code, 0)
        self.assertTrue(callbacks.reader_connections[0].connected)
        self.assertEqual(callbacks.reader_connections[0].reader_name, "ACS ACR1255U-J1 00 00")
        self.assertEqual(callbacks.detected[0].uid, "04123456")
        self.assertEqual(callbacks.detected[0].atr, "3B8F8001")
        self.assertEqual(callbacks.removed, ["ACS ACR1255U-J1 00 00"])
        self.assertEqual(connection.last_apdu, identify_tag.GET_UID_APDU)
        self.assertIsNotNone(card_monitor.deleted_observer)

    def test_monitor_emits_tag_context_after_successful_uid_read(self) -> None:
        stop_event = threading.Event()
        callbacks = RecordingCallbacks(stop_event, stop_on_tag_available=True)
        connection = FakeConnection(data=[0x04, 0x12, 0x34, 0x56])
        card = FakeCard(connection)
        card_monitor = FakeCardMonitor(added_cards=[card])
        pcsc = make_pcsc(readers=["ACS ACR1255U-J1 00 00"], monitor=card_monitor)

        exit_code = rfid_monitor.RfidMonitor(pcsc, event_timeout_seconds=0.01).run(callbacks, stop_event)

        self.assertEqual(exit_code, 0)
        self.assertEqual(callbacks.tag_contexts[0].identity.uid, "04123456")
        self.assertIs(callbacks.tag_contexts[0].card, card)


if __name__ == "__main__":
    unittest.main()
