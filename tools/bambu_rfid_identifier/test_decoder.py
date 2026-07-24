from __future__ import annotations

import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path

import bambu_catalogue
import catalogue_loader
import decoder
import memory_inspector


class DecoderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_dir = tempfile.TemporaryDirectory()
        self.original_cache_dir = catalogue_loader.DEFAULT_CACHE_DIR
        catalogue_loader.DEFAULT_CACHE_DIR = Path(self.cache_dir.name)

    def tearDown(self) -> None:
        catalogue_loader.DEFAULT_CACHE_DIR = self.original_cache_dir
        self.cache_dir.cleanup()

    def test_decodes_valid_representative_dump(self) -> None:
        payload = representative_dump()

        decoded = decoder.decode_dump_dict(payload)
        fields = field_values(decoded)

        self.assertEqual(decoded.errors, [])
        self.assertEqual(fields["tray_info_variant_id"], "A00-B9")
        self.assertEqual(fields["tray_info_material_id"], "GFA00")
        self.assertEqual(fields["filament_type"], "PLA")
        self.assertEqual(fields["detailed_filament_type"], "PLA Basic")
        self.assertEqual(fields["color_rgba"]["hex"], "0A2989FF")
        self.assertEqual(fields["spool_weight_grams"], 1000)
        self.assertAlmostEqual(fields["filament_diameter_mm"], 1.75)
        self.assertEqual(fields["drying_temperature_c"], 55)
        self.assertEqual(fields["drying_time_hours"], 8)
        self.assertEqual(fields["bed_temperature_type"], 1)
        self.assertEqual(fields["bed_temperature_c"], 35)
        self.assertEqual(fields["hotend_max_temperature_c"], 230)
        self.assertEqual(fields["hotend_min_temperature_c"], 190)
        self.assertAlmostEqual(fields["minimum_nozzle_diameter_mm"], 0.4)
        self.assertEqual(fields["tray_uid"], "54524159313233343536373839300000")
        self.assertEqual(fields["spool_width_mm"], 66.25)
        self.assertEqual(fields["production_datetime"], "2024_05_01_1200")
        self.assertEqual(fields["short_production_datetime"], "20240501")
        self.assertEqual(fields["extra_color_format_identifier"], 2)
        self.assertEqual(fields["extra_color_count"], 2)
        self.assertEqual(fields["second_color_rgba"]["hex"], "11223344")
        self.assertEqual(fields["manufacturer"], "Bambu Lab")
        self.assertEqual(fields["catalogue_name"], "Bambu Lab PLA Basic Blue")
        self.assertEqual(fields["material_name"], "PLA Basic")
        self.assertEqual(fields["color_name"], "Blue")
        self.assertEqual(fields["catalogue_match_status"], "exact")
        self.assertEqual(fields["catalogue_match_source"], "bundled validated fallback")
        self.assertEqual(fields["catalogue_entry_id"], "A00-B9")
        self.assertEqual(fields["catalogue_source_repository"], "TL3D bundled validated fallback")

    def test_malformed_hex_produces_warning_instead_of_crashing(self) -> None:
        payload = representative_dump()
        payload["sectors"][1]["blocks"][1]["data_hex"] = "not hex"

        decoded = decoder.decode_dump_dict(payload)

        self.assertEqual(decoded.errors, [])
        self.assertTrue(any("invalid hexadecimal" in warning for warning in decoded.warnings))
        self.assertNotIn("spool_weight_grams", field_values(decoded))

    def test_missing_blocks_and_incomplete_sectors_warn(self) -> None:
        payload = representative_dump()
        payload["sectors"][1]["blocks"] = payload["sectors"][1]["blocks"][:2]
        payload["sectors"] = payload["sectors"][:15]

        decoded = decoder.decode_dump_dict(payload)

        self.assertTrue(any("Sector 1 is incomplete" in warning for warning in decoded.warnings))
        self.assertTrue(any("missing sectors [15]" in warning for warning in decoded.warnings))

    def test_unknown_reserved_trailer_and_signature_bytes_are_preserved(self) -> None:
        decoded = decoder.decode_dump_dict(representative_dump())
        raw = {(item.name, item.source): item.data_hex for item in decoded.raw_unknown}

        self.assertIn(("manufacturer_block", "sector 0 block 0 absolute 0"), raw)
        self.assertIn(("mifare_sector_trailer", "sector 1 block 3 absolute 7"), raw)
        self.assertIn(("filament_length_uncertain", "sector 3 block 2 absolute 14"), raw)
        self.assertIn(("unknown_block_17", "sector 4 block 1 absolute 17"), raw)
        self.assertIn(("rsa_signature_block", "sector 10 block 0 absolute 40"), raw)

    def test_rsa_signature_region_is_assembled_without_trailers(self) -> None:
        payload = representative_dump()

        decoded = decoder.decode_dump_dict(payload)
        signature = decoded.rsa_signature

        self.assertIsNotNone(signature)
        assert signature is not None
        self.assertEqual(signature.status, "complete")
        self.assertEqual(signature.expected_length_bytes, 256)
        self.assertEqual(signature.available_length_bytes, 256)
        self.assertEqual(len(signature.hex), 512)
        self.assertFalse(signature.verified)
        self.assertEqual(signature.verification_status, "not_implemented")
        self.assertFalse(any(block.block == 3 and block.included_in_signature_hex for block in signature.blocks))
        self.assertNotIn("87878769", signature.hex)

    def test_rsa_signature_partial_when_required_payload_block_unreadable(self) -> None:
        payload = representative_dump()
        block = payload["sectors"][10]["blocks"][1]
        block["status"] = "read_failed"
        block["data_hex"] = None
        block["error"] = "read_failed. Status: 63 00"

        decoded = decoder.decode_dump_dict(payload)
        signature = decoded.rsa_signature

        self.assertIsNotNone(signature)
        assert signature is not None
        self.assertEqual(signature.status, "partial")
        self.assertEqual(signature.expected_length_bytes, 256)
        self.assertEqual(signature.available_length_bytes, 240)
        self.assertTrue(any("RSA signature data is partial" in warning for warning in decoded.warnings))

    def test_rsa_signature_does_not_assert_cryptographic_validity(self) -> None:
        decoded = decoder.decode_dump_dict(representative_dump())

        self.assertIsNotNone(decoded.rsa_signature)
        assert decoded.rsa_signature is not None
        self.assertFalse(decoded.rsa_signature.verified)
        self.assertEqual(decoded.rsa_signature.verification_status, "not_implemented")

    def test_little_endian_numeric_conversion(self) -> None:
        payload = representative_dump()
        decoded = decoder.decode_dump_dict(payload)
        fields = field_values(decoded)

        self.assertEqual(fields["spool_weight_grams"], 1000)
        self.assertAlmostEqual(fields["filament_diameter_mm"], 1.75, places=6)
        self.assertEqual(fields["spool_width_mm"], 66.25)

    def test_filament_diameter_uses_four_byte_little_endian_float(self) -> None:
        payload = representative_dump()
        block5 = bytearray(16)
        block5[0:4] = bytes.fromhex("0A2989FF")
        block5[4:6] = (1000).to_bytes(2, "little")
        block5[8:12] = bytes.fromhex("0000E03F")
        block5[12:16] = bytes.fromhex("DEADBEEF")
        set_block(payload, 1, 1, block5)

        decoded = decoder.decode_dump_dict(payload)
        diameter = field_values(decoded)["filament_diameter_mm"]

        self.assertAlmostEqual(diameter, 1.75, places=6)

    def test_filament_diameter_does_not_regress_to_double_read(self) -> None:
        payload = representative_dump()

        decoded = decoder.decode_dump_dict(payload)
        diameter = field_values(decoded)["filament_diameter_mm"]

        self.assertGreater(diameter, 1.0)
        self.assertNotAlmostEqual(diameter, 5.29462817e-315)

    def test_short_filament_diameter_field_warns_without_crashing(self) -> None:
        payload = representative_dump()
        payload["sectors"][1]["blocks"][1]["data_hex"] = "0A2989FFE80300000000"

        decoded = decoder.decode_dump_dict(payload)
        fields = field_values(decoded)

        self.assertNotIn("filament_diameter_mm", fields)
        self.assertTrue(any("Cannot decode filament_diameter_mm" in warning for warning in decoded.warnings))

    def test_catalogue_resolves_pumpkin_orange_without_generic_colour_guessing(self) -> None:
        payload = catalogue_payload("PLA Basic Pumpkin Orange")

        decoded = decoder.decode_dump_dict(payload)
        fields = field_values(decoded)

        self.assertEqual(fields["catalogue_match_status"], "exact")
        self.assertEqual(fields["catalogue_name"], "Bambu Lab PLA Basic Pumpkin Orange")
        self.assertEqual(fields["color_name"], "Pumpkin Orange")
        self.assertNotEqual(fields["color_name"], "Orange")

    def test_catalogue_resolves_validated_entries_across_material_families(self) -> None:
        expected_names = {
            "PLA Basic Blue": "Bambu Lab PLA Basic Blue",
            "PLA Basic Hot Pink": "Bambu Lab PLA Basic Hot Pink",
            "PLA Basic Green": "Bambu Lab PLA Basic Green",
            "PLA Basic Pumpkin Orange": "Bambu Lab PLA Basic Pumpkin Orange",
            "PLA Basic Bright Green": "Bambu Lab PLA Basic Bright Green",
            "PLA Matte Desert Tan": "Bambu Lab PLA Matte Desert Tan",
            "PLA Matte Charcoal": "Bambu Lab PLA Matte Charcoal",
            "PLA Matte Terracotta": "Bambu Lab PLA Matte Terracotta",
            "PLA Silk+ Silver": "Bambu Lab PLA Silk+ Silver",
            "PETG Basic Gray": "Bambu Lab PETG Basic Gray",
            "PETG Basic Blue": "Bambu Lab PETG Basic Blue",
            "PETG Basic Yellow": "Bambu Lab PETG Basic Yellow",
            "PETG HF Black": "Bambu Lab PETG HF Black",
        }

        for label, expected_name in expected_names.items():
            with self.subTest(label=label):
                decoded = decoder.decode_dump_dict(catalogue_payload(label))
                fields = field_values(decoded)
                self.assertEqual(fields["catalogue_match_status"], "exact")
                self.assertEqual(fields["catalogue_name"], expected_name)

    def test_unknown_catalogue_identifiers_do_not_invent_a_name(self) -> None:
        payload = representative_dump()
        set_block(payload, 0, 1, b"ZZZ-ZZ\x00\x00" + b"GFZZZ\x00\x00\x00")

        decoded = decoder.decode_dump_dict(payload)
        fields = field_values(decoded)

        self.assertEqual(fields["catalogue_match_status"], "unknown")
        self.assertIsNone(fields["catalogue_name"])
        self.assertIsNone(fields["color_name"])

    def test_conflicting_catalogue_identifier_and_rgba_returns_warning_status(self) -> None:
        payload = representative_dump()
        block5 = bytearray(bytes.fromhex(payload["sectors"][1]["blocks"][1]["data_hex"]))
        block5[0:4] = bytes.fromhex("FF9016FF")
        set_block(payload, 1, 1, block5)

        decoded = decoder.decode_dump_dict(payload)
        fields = field_values(decoded)

        self.assertEqual(fields["catalogue_match_status"], "identifier_match_with_warning")
        self.assertEqual(fields["catalogue_name"], "Bambu Lab PLA Basic Blue")
        self.assertTrue(any("differs from catalogue colour" in warning for warning in decoded.warnings))

    def test_partial_dump_without_catalogue_identifiers_returns_unknown(self) -> None:
        payload = representative_dump()
        payload["sectors"][0]["blocks"][1]["status"] = "read_failed"
        payload["sectors"][0]["blocks"][1]["data_hex"] = None
        payload["sectors"][0]["blocks"][1]["error"] = "read_failed. Status: 63 00"

        decoded = decoder.decode_dump_dict(payload)
        fields = field_values(decoded)

        self.assertEqual(fields["catalogue_match_status"], "unknown")
        self.assertIsNone(fields["catalogue_name"])
        self.assertTrue(any("missing tray_info_variant_id" in warning for warning in decoded.warnings))

    def test_default_report_is_concise_human_readable(self) -> None:
        report = decoder.format_human_readable(decoder.decode_dump_dict(catalogue_payload("PLA Basic Pumpkin Orange")))

        self.assertIn("Bambu RFID Filament Report", report)
        self.assertIn("Filament", report)
        self.assertIn("Full name", report)
        self.assertIn("Bambu Lab PLA Basic Pumpkin Orange", report)
        self.assertIn("Catalogue match           : ✓ Exact", report)
        self.assertIn("Nozzle range              : 190–230 °C", report)
        self.assertIn("Drying                    : 55 °C for 8 hours", report)
        self.assertIn("Signature                 : Complete (256 bytes)", report)
        self.assertIn("Verified                  : No", report)
        self.assertNotIn("Catalogue source", report)
        self.assertNotIn("Cryptographically verified", report)
        self.assertNotIn("Decoded fields:", report)

    def test_verbose_report_preserves_technical_output(self) -> None:
        report = decoder.format_verbose(decoder.decode_dump_dict(representative_dump()))

        self.assertIn("Bambu RFID Decoded Dump", report)
        self.assertIn("Decoded fields:", report)
        self.assertIn("Preserved raw/unknown data:", report)

    def test_tray_uid_binary_value_does_not_warn_as_ascii(self) -> None:
        payload = representative_dump()
        set_block(payload, 2, 1, bytes.fromhex("1AB6889BD66D41919D59EF8DEF1FB1CB"))

        decoded = decoder.decode_dump_dict(payload)

        self.assertEqual(field_values(decoded)["tray_uid"], "1AB6889BD66D41919D59EF8DEF1FB1CB")
        self.assertFalse(any("tray_uid as ASCII" in warning for warning in decoded.warnings))

    def test_string_decoding_trims_nulls_and_spaces(self) -> None:
        payload = representative_dump()
        block = bytearray(16)
        block[0:16] = b"PLA Basic \x00\x00\x00\x00\x00\x00"
        set_block(payload, 1, 0, block)

        decoded = decoder.decode_dump_dict(payload)

        self.assertEqual(field_values(decoded)["detailed_filament_type"], "PLA Basic")

    def test_source_dump_is_not_mutated(self) -> None:
        payload = representative_dump()
        original = copy.deepcopy(payload)

        decoder.decode_dump_dict(payload)

        self.assertEqual(payload, original)

    def test_malformed_json_file_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text("{not json", encoding="utf-8")

            decoded = decoder.decode_file(path)

        self.assertTrue(decoded.errors)
        self.assertIn("Malformed JSON", decoded.errors[0])

    def test_unsupported_schema_version_reports_error(self) -> None:
        payload = representative_dump()
        payload["schema_version"] = 999

        decoded = decoder.decode_dump_dict(payload)

        self.assertTrue(any("Unsupported dump schema version" in error for error in decoded.errors))

    def test_decode_raw_dump_accepts_existing_in_memory_model(self) -> None:
        dump = memory_inspector.RawDump(
            schema_version=1,
            created_at="2026-07-23T12:00:00+00:00",
            reader_name="reader",
            uid="04123456",
            atr="3B8F8001",
            tag_type="MIFARE Classic 1K (assumed from Bambu workflow)",
            upstream_reference=memory_inspector.upstream_reference(),
            sectors=[
                memory_inspector.SectorDump(
                    sector=0,
                    authentication_status="success",
                    blocks=[
                        memory_inspector.BlockDump(
                            block=2,
                            absolute_block=2,
                            status="success",
                            data_hex=hex_block(ascii_block("PLA")),
                        )
                    ],
                )
            ],
            status="success",
            error=None,
            software={"tool": memory_inspector.TOOL_VERSION},
        )

        decoded = decoder.decode_raw_dump(dump)

        self.assertEqual(field_values(decoded)["filament_type"], "PLA")

    def test_json_output_shape_is_serializable(self) -> None:
        decoded = decoder.decode_dump_dict(representative_dump())
        encoded = json.dumps(decoded.to_dict())

        self.assertIn("decoded", encoded)
        self.assertIn("filament_type", encoded)


def field_values(decoded: decoder.DecodedDump) -> dict[str, object]:
    return {item.name: item.value for item in decoded.fields}


def representative_dump() -> dict[str, object]:
    payload = {
        "schema_version": 1,
        "created_at": "2026-07-23T12:00:00+00:00",
        "reader_name": "ACS ACR1255U-J1 00 00",
        "uid": "04123456",
        "atr": "3B8F8001",
        "tag_type": "MIFARE Classic 1K (assumed from Bambu workflow)",
        "upstream_reference": memory_inspector.upstream_reference(),
        "sectors": [],
        "status": "success",
        "error": None,
        "software": {"tool": memory_inspector.TOOL_VERSION},
    }

    for sector in range(16):
        payload["sectors"].append(
            {
                "sector": sector,
                "authentication_status": "success",
                "blocks": [
                    {
                        "block": block,
                        "absolute_block": sector * 4 + block,
                        "status": "success",
                        "data_hex": "00" * 16,
                    }
                    for block in range(4)
                ],
            }
        )

    manufacturer = bytes.fromhex("04123456") + bytes.fromhex("AABBCCDDEEFF001122334455")
    set_block(payload, 0, 0, manufacturer)
    set_block(payload, 0, 1, b"A00-B9\x00\x00" + b"GFA00\x00\x00\x00")
    set_block(payload, 0, 2, ascii_block("PLA"))
    set_block(payload, 1, 0, ascii_block("PLA Basic"))

    block5 = bytearray(16)
    block5[0:4] = bytes.fromhex("0A2989FF")
    block5[4:6] = (1000).to_bytes(2, "little")
    block5[8:12] = struct.pack("<f", 1.75)
    set_block(payload, 1, 1, block5)

    block6 = bytearray(16)
    for offset, value in [(0, 55), (2, 8), (4, 1), (6, 35), (8, 230), (10, 190)]:
        block6[offset : offset + 2] = value.to_bytes(2, "little")
    set_block(payload, 1, 2, block6)

    block8 = bytearray.fromhex("0102030405060708090A0B0C") + bytearray(struct.pack("<f", 0.4))
    set_block(payload, 2, 0, block8)
    set_block(payload, 2, 1, ascii_block("TRAY1234567890"))

    block10 = bytearray(16)
    block10[4:6] = (6625).to_bytes(2, "little")
    set_block(payload, 2, 2, block10)

    set_block(payload, 3, 0, ascii_block("2024_05_01_1200"))
    set_block(payload, 3, 1, ascii_block("20240501"))

    block14 = bytearray(16)
    block14[4:6] = (330).to_bytes(2, "little")
    set_block(payload, 3, 2, block14)

    block16 = bytearray(16)
    block16[0:2] = (2).to_bytes(2, "little")
    block16[2:4] = (2).to_bytes(2, "little")
    block16[4:8] = bytes.fromhex("44332211")
    set_block(payload, 4, 0, block16)

    block17 = bytearray(16)
    block17[0:2] = bytes.fromhex("BEEF")
    set_block(payload, 4, 1, block17)
    set_signature_region(payload)
    return payload


def ascii_block(value: str) -> bytes:
    return value.encode("ascii").ljust(16, b"\x00")


def hex_block(value: bytes) -> str:
    return value.hex().upper()


def set_block(payload: dict[str, object], sector: int, block: int, data: bytes | bytearray) -> None:
    assert len(data) == 16
    payload["sectors"][sector]["blocks"][block]["data_hex"] = bytes(data).hex().upper()


def set_signature_region(payload: dict[str, object]) -> None:
    payload_index = 0
    for sector in range(10, 16):
        for block in range(4):
            if block == 3:
                set_block(payload, sector, block, bytes.fromhex("00000000000087878769000000000000"))
                continue

            data = bytes([payload_index % 256]) * 16
            set_block(payload, sector, block, data)
            payload_index += 1


def catalogue_payload(label: str) -> dict[str, object]:
    entry = {
        f"{item.material_name} {item.color_name}": item for item in bambu_catalogue.CATALOGUE
    }[label]
    payload = representative_dump()
    variant = entry.tray_info_variant_id.encode("ascii").ljust(8, b"\x00")
    material = entry.tray_info_material_id.encode("ascii").ljust(8, b"\x00")
    set_block(payload, 0, 1, variant + material)
    set_block(payload, 0, 2, ascii_block(entry.filament_type))
    set_block(payload, 1, 0, ascii_block(entry.detailed_filament_type))
    block5 = bytearray(bytes.fromhex(payload["sectors"][1]["blocks"][1]["data_hex"]))
    block5[0:4] = bytes.fromhex(entry.color_rgba)
    set_block(payload, 1, 1, block5)
    return payload


if __name__ == "__main__":
    unittest.main()
