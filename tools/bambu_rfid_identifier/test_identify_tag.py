from __future__ import annotations

import unittest
from types import SimpleNamespace

import identify_tag


class FakePcscException(Exception):
    pass


class FakeCardConnection:
    T1_protocol = object()


FAKE_PCSC = identify_tag.PcscApi(
    card_connection=FakeCardConnection,
    card_monitor=lambda: None,
    card_connection_exception=FakePcscException,
    no_card_exception=FakePcscException,
    no_readers_exception=FakePcscException,
    readers=lambda: [],
)


class FakeConnection:
    def __init__(self, *, data=None, status=(0x90, 0x00), fail_connect=False, fail_transmit=False) -> None:
        self.data = [] if data is None else data
        self.status = status
        self.fail_connect = fail_connect
        self.fail_transmit = fail_transmit
        self.connected_with_t1 = False
        self.disconnected = False

    def connect(self, protocol=None) -> None:
        if self.fail_connect:
            raise FakePcscException("connect failed")
        if protocol is FakeCardConnection.T1_protocol:
            self.connected_with_t1 = True

    def transmit(self, apdu):
        if self.fail_transmit:
            raise FakePcscException("transmit failed")
        self.last_apdu = apdu
        sw1, sw2 = self.status
        return self.data, sw1, sw2

    def disconnect(self) -> None:
        self.disconnected = True


class FakeCard:
    def __init__(self, connection: FakeConnection) -> None:
        self.reader = "ACS ACR1255U-J1 00 00"
        self.atr = [0x3B, 0x8F, 0x80, 0x01]
        self.connection = connection

    def createConnection(self) -> FakeConnection:
        return self.connection


class IdentifyTagTests(unittest.TestCase):
    def test_bytes_to_hex(self) -> None:
        self.assertEqual(identify_tag.bytes_to_hex([0x04, 0xA1, 0x00, 0xFE]), "04A100FE")

    def test_select_reader_finds_acr1255_case_insensitive(self) -> None:
        reader = identify_tag.select_reader(
            ["Other Reader", "ACS ACR1255U-J1 00 00"],
            reader_name="acr1255u-j1",
            any_reader=False,
        )
        self.assertEqual(reader, "ACS ACR1255U-J1 00 00")

    def test_select_reader_can_use_any_reader(self) -> None:
        reader = identify_tag.select_reader(["Development Reader"], reader_name="ACR1255U-J1", any_reader=True)
        self.assertEqual(reader, "Development Reader")

    def test_identify_card_reads_uid_with_read_only_get_data_apdu(self) -> None:
        connection = FakeConnection(data=[0x04, 0x12, 0x34, 0x56, 0x78, 0x90, 0xAB])
        identity = identify_tag.identify_card(FakeCard(connection), FAKE_PCSC)

        self.assertEqual(identity.reader_name, "ACS ACR1255U-J1 00 00")
        self.assertEqual(identity.atr, "3B8F8001")
        self.assertEqual(identity.uid, "041234567890AB")
        self.assertIsNone(identity.uid_error)
        self.assertEqual(connection.last_apdu, identify_tag.GET_UID_APDU)
        self.assertTrue(connection.connected_with_t1)
        self.assertTrue(connection.disconnected)

    def test_identify_card_reports_unsupported_uid_status(self) -> None:
        connection = FakeConnection(status=(0x6A, 0x81))
        identity = identify_tag.identify_card(FakeCard(connection), FAKE_PCSC)

        self.assertIsNone(identity.uid)
        self.assertEqual(identity.atr, "3B8F8001")
        self.assertIn("Status: 6A 81", identity.uid_error or "")

    def test_identify_card_reports_connection_error(self) -> None:
        connection = FakeConnection(fail_connect=True)
        identity = identify_tag.identify_card(FakeCard(connection), FAKE_PCSC)

        self.assertIsNone(identity.uid)
        self.assertIn("Could not connect", identity.uid_error or "")

    def test_card_event_observer_queues_add_and_remove_events(self) -> None:
        events = identify_tag.queue.Queue()
        observer = identify_tag.CardEventObserver(events)
        added = SimpleNamespace(reader="reader", atr=[])
        removed = SimpleNamespace(reader="reader", atr=[])

        observer.update(object(), ([added], [removed]))

        self.assertEqual(events.get_nowait(), ("added", added))
        self.assertEqual(events.get_nowait(), ("removed", removed))


if __name__ == "__main__":
    unittest.main()
