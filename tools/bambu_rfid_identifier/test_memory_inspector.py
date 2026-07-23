from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import identify_tag
import memory_inspector


class FakePcscException(Exception):
    pass


class FakeNoCardException(Exception):
    pass


class FakeCardConnection:
    T1_protocol = object()


FAKE_PCSC = identify_tag.PcscApi(
    card_connection=FakeCardConnection,
    card_monitor=lambda: None,
    card_connection_exception=FakePcscException,
    no_card_exception=FakeNoCardException,
    no_readers_exception=FakePcscException,
    readers=lambda: [],
)


class FakeCard:
    def __init__(self, connection, *, reader="ACS ACR1255U-J1 00 00") -> None:
        self.reader = reader
        self.connection = connection

    def createConnection(self):
        return self.connection


class ScriptedConnection:
    def __init__(self, responses=None, *, fail_connect=False) -> None:
        self.responses = [] if responses is None else list(responses)
        self.fail_connect = fail_connect
        self.apdus: list[list[int]] = []
        self.disconnected = False

    def connect(self, protocol=None) -> None:
        if self.fail_connect:
            raise FakePcscException("connect failed")

    def transmit(self, apdu):
        self.apdus.append(apdu)
        if not self.responses:
            return [0x00] * 16, 0x90, 0x00
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def disconnect(self) -> None:
        self.disconnected = True


class MemoryInspectorTests(unittest.TestCase):
    def test_valid_uid_handling_accepts_reader_hex_format(self) -> None:
        self.assertEqual(memory_inspector.validate_uid_hex("04 12:34 56"), bytes.fromhex("04123456"))

    def test_invalid_uid_handling_rejects_bad_hex_and_length(self) -> None:
        with self.assertRaisesRegex(ValueError, "hexadecimal"):
            memory_inspector.validate_uid_hex("04123X56")
        with self.assertRaisesRegex(ValueError, "Unsupported UID length"):
            memory_inspector.validate_uid_hex("041234")

    def test_key_derivation_is_deterministic_for_documented_hkdf_inputs(self) -> None:
        keys = memory_inspector.derive_bambu_sector_keys(bytes.fromhex("04123456"))

        self.assertEqual(len(keys), 16)
        self.assertEqual(keys[0].key_a.hex().upper(), "01CA90ABBF72")
        self.assertEqual(keys[1].key_a.hex().upper(), "93D44C7A2403")
        self.assertEqual(keys[0].key_b.hex().upper(), "D08B6089680F")

    def test_acs_apdu_builders_use_key_load_authenticate_and_read_only_commands(self) -> None:
        key = bytes.fromhex("01CA90ABBF72")

        self.assertEqual(memory_inspector.load_key_apdu(key), [0xFF, 0x82, 0x00, 0x00, 0x06, 0x01, 0xCA, 0x90, 0xAB, 0xBF, 0x72])
        self.assertEqual(memory_inspector.authenticate_key_a_apdu(4), [0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, 0x04, 0x60, 0x00])
        self.assertEqual(memory_inspector.read_binary_apdu(4), [0xFF, 0xB0, 0x00, 0x04, 0x10])

    def test_no_write_commands_are_exposed_by_new_apdu_builders(self) -> None:
        apdus = [
            memory_inspector.load_key_apdu(bytes.fromhex("01CA90ABBF72")),
            memory_inspector.authenticate_key_a_apdu(0),
            memory_inspector.read_binary_apdu(0),
        ]

        self.assertFalse(any(tuple(apdu[:2]) in memory_inspector.WRITE_APDU_PREFIXES for apdu in apdus))

    def test_successful_sector_authentication_and_block_reads_are_grouped(self) -> None:
        connection = ScriptedConnection()
        identity = identify_tag.TagIdentity("ACS ACR1255U-J1 00 00", "3B8F8001", "04123456")

        dump = memory_inspector.BambuMemoryInspector().inspect_card(FakeCard(connection), FAKE_PCSC, identity)

        self.assertEqual(dump.status, "success")
        self.assertEqual(len(dump.sectors), 16)
        self.assertEqual(len(dump.sectors[0].blocks), 4)
        self.assertEqual(dump.sectors[0].authentication_status, "success")
        self.assertEqual(dump.sectors[0].blocks[0].status, "success")
        self.assertEqual(dump.sectors[0].blocks[0].data_hex, "00000000000000000000000000000000")
        self.assertEqual(connection.apdus[0][0:5], [0xFF, 0x82, 0x00, 0x00, 0x06])
        self.assertEqual(connection.apdus[1], memory_inspector.authenticate_key_a_apdu(0))
        self.assertEqual(connection.apdus[2], memory_inspector.read_binary_apdu(0))
        self.assertTrue(connection.disconnected)

    def test_authentication_failure_marks_every_sector_block(self) -> None:
        connection = ScriptedConnection([((), 0x90, 0x00), ((), 0x63, 0x00)])
        identity = identify_tag.TagIdentity("ACS ACR1255U-J1 00 00", "3B8F8001", "04123456")

        dump = memory_inspector.BambuMemoryInspector().inspect_card(FakeCard(connection), FAKE_PCSC, identity)

        self.assertEqual(dump.status, "partial")
        self.assertEqual(dump.sectors[0].authentication_status, "authentication_failed")
        self.assertEqual([block.status for block in dump.sectors[0].blocks], ["authentication_failed"] * 4)
        self.assertIn("Status: 63 00", dump.sectors[0].error or "")

    def test_failed_block_read_is_recorded_without_skipping(self) -> None:
        connection = ScriptedConnection([((), 0x90, 0x00), ((), 0x90, 0x00), ((), 0x6A, 0x82)])
        identity = identify_tag.TagIdentity("ACS ACR1255U-J1 00 00", "3B8F8001", "04123456")

        dump = memory_inspector.BambuMemoryInspector().inspect_card(FakeCard(connection), FAKE_PCSC, identity)

        block = dump.sectors[0].blocks[0]
        self.assertEqual(block.status, "read_failed")
        self.assertIsNone(block.data_hex)
        self.assertIn("Status: 6A 82", block.error or "")

    def test_tag_removal_during_dump_is_reported(self) -> None:
        connection = ScriptedConnection([((), 0x90, 0x00), FakeNoCardException("tag gone")])
        identity = identify_tag.TagIdentity("ACS ACR1255U-J1 00 00", "3B8F8001", "04123456")

        dump = memory_inspector.BambuMemoryInspector().inspect_card(FakeCard(connection), FAKE_PCSC, identity)

        self.assertEqual(dump.status, "partial")
        self.assertEqual(dump.sectors[0].authentication_status, "tag_removed")
        self.assertIn("Tag removed", dump.error or "")

    def test_reader_disconnection_during_dump_is_reported(self) -> None:
        connection = ScriptedConnection([FakePcscException("reader lost")])
        identity = identify_tag.TagIdentity("ACS ACR1255U-J1 00 00", "3B8F8001", "04123456")

        dump = memory_inspector.BambuMemoryInspector().inspect_card(FakeCard(connection), FAKE_PCSC, identity)

        self.assertEqual(dump.status, "partial")
        self.assertEqual(dump.sectors[0].authentication_status, "reader_error")
        self.assertIn("Reader disconnected", dump.error or "")

    def test_unsupported_tag_type_without_uid_is_reported(self) -> None:
        identity = identify_tag.TagIdentity("ACS ACR1255U-J1 00 00", "3B8F8001", None)

        dump = memory_inspector.BambuMemoryInspector().inspect_card(FakeCard(ScriptedConnection()), FAKE_PCSC, identity)

        self.assertEqual(dump.status, "unsupported_tag")
        self.assertEqual(dump.tag_type, "unknown")
        self.assertIn("UID is required", dump.error or "")

    def test_format_dump_lines_includes_sector_block_and_hex(self) -> None:
        dump = sample_dump()

        lines = memory_inspector.format_dump_lines(dump)

        self.assertIn("UID: 04123456", lines)
        self.assertIn("Sector 01: success", lines)
        self.assertIn("  Block 2 absolute 06 success: 00112233445566778899AABBCCDDEEFF", lines)

    def test_json_serialization_includes_required_schema_and_grouping(self) -> None:
        dump = sample_dump()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = memory_inspector.save_memory_dump(dump, Path(temp_dir))
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(path.name.startswith("bambu_rfid_dump_04123456_"))
        self.assertEqual(path.suffix, ".json")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["reader_name"], "reader")
        self.assertEqual(payload["uid"], "04123456")
        self.assertEqual(payload["atr"], "3B8F8001")
        self.assertEqual(payload["tag_type"], "MIFARE Classic 1K (assumed from Bambu workflow)")
        self.assertEqual(payload["upstream_reference"]["project"], "Bambu-Lab-RFID-Tag-Guide")
        self.assertEqual(payload["sectors"][0]["sector"], 1)
        self.assertEqual(payload["sectors"][0]["blocks"][0]["block"], 2)
        self.assertEqual(payload["sectors"][0]["blocks"][0]["data_hex"], "00112233445566778899AABBCCDDEEFF")
        self.assertEqual(payload["sectors"][0]["blocks"][0]["status"], "success")


def sample_dump() -> memory_inspector.RawDump:
    return memory_inspector.RawDump(
        schema_version=1,
        created_at="2026-07-23T12:00:00+00:00",
        reader_name="reader",
        uid="04123456",
        atr="3B8F8001",
        tag_type="MIFARE Classic 1K (assumed from Bambu workflow)",
        upstream_reference=memory_inspector.upstream_reference(),
        sectors=[
            memory_inspector.SectorDump(
                sector=1,
                authentication_status="success",
                blocks=[
                    memory_inspector.BlockDump(
                        block=2,
                        absolute_block=6,
                        status="success",
                        data_hex="00112233445566778899AABBCCDDEEFF",
                    )
                ],
            )
        ],
        status="success",
        error=None,
        software={"tool": memory_inspector.TOOL_VERSION},
    )


if __name__ == "__main__":
    unittest.main()
