from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.importers.three_dfp import SPOOL_UUID_COMMENT_MARKER, ThreeDfpImporter, main, parse_csv, spool_uuid_marker
from app.spoolman_client import (
    BackupResponse,
    CreateFilamentRequest,
    CreateSpoolRequest,
    CreateVendorRequest,
    Filament,
    Spool,
    Vendor,
)

FIXTURE = Path(__file__).parent / "fixtures" / "three_dfp_inventory.csv"


class FakeSpoolmanClient:
    def __init__(
        self,
        *,
        vendors: list[Vendor] | None = None,
        filaments: list[Filament] | None = None,
        spools: list[Spool] | None = None,
    ) -> None:
        self.vendors = vendors or []
        self.filaments = filaments or []
        self.spools = spools or []
        self.created_vendors: list[CreateVendorRequest] = []
        self.created_filaments: list[CreateFilamentRequest] = []
        self.created_spools: list[CreateSpoolRequest] = []
        self.backups_created = 0

    def list_vendors(self) -> list[Vendor]:
        return list(self.vendors)

    def list_filaments(self) -> list[Filament]:
        return list(self.filaments)

    def list_spools(self, *, allow_archived: bool = False) -> list[Spool]:
        self.allow_archived = allow_archived
        return list(self.spools)

    def create_backup(self) -> BackupResponse:
        self.backups_created += 1
        return BackupResponse(path="/backups/spoolman.db")

    def create_vendor(self, request: CreateVendorRequest) -> Vendor:
        self.created_vendors.append(request)
        vendor = Vendor(id=len(self.vendors) + 1, registered="2026-07-16T12:00:00Z", name=request.name, extra={})
        self.vendors.append(vendor)
        return vendor

    def create_filament(self, request: CreateFilamentRequest) -> Filament:
        self.created_filaments.append(request)
        vendor = next((vendor for vendor in self.vendors if vendor.id == request.vendor_id), None)
        filament = Filament(
            id=len(self.filaments) + 1,
            registered="2026-07-16T12:00:00Z",
            density=request.density,
            diameter=request.diameter,
            name=request.name,
            vendor=vendor,
            material=request.material,
            price=request.price,
            weight=request.weight,
            spool_weight=request.spool_weight,
            article_number=request.article_number,
            comment=request.comment,
            settings_extruder_temp=request.settings_extruder_temp,
            settings_bed_temp=request.settings_bed_temp,
            color_hex=request.color_hex,
            multi_color_hexes=request.multi_color_hexes,
            multi_color_direction=request.multi_color_direction,
            external_id=request.external_id,
            extra={},
        )
        self.filaments.append(filament)
        return filament

    def create_spool(self, request: CreateSpoolRequest) -> Spool:
        self.created_spools.append(request)
        filament = next(filament for filament in self.filaments if filament.id == request.filament_id)
        spool = Spool(
            id=len(self.spools) + 1,
            registered="2026-07-16T12:00:00Z",
            filament=filament,
            used_weight=0,
            used_length=0,
            archived=request.archived or False,
            price=request.price,
            remaining_weight=request.remaining_weight,
            initial_weight=request.initial_weight,
            spool_weight=request.spool_weight,
            location=request.location,
            comment=request.comment,
            extra={},
        )
        self.spools.append(spool)
        return spool


class ThreeDfpImporterTests(unittest.TestCase):
    def test_parse_csv_returns_rows_and_row_level_errors(self) -> None:
        rows, errors, rows_seen = parse_csv(FIXTURE)

        self.assertEqual(rows_seen, 4)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].row_number, 5)
        self.assertIn("manufacturer", errors[0].message)
        self.assertEqual(rows[0].manufacturer, "Polymaker")
        self.assertEqual(rows[0].color_hex, "222222")
        self.assertEqual(rows[1].multi_color_hexes, "FF0000,00FF00")
        self.assertEqual(rows[1].multi_color_direction, "coaxial")
        self.assertEqual(rows[0].spool_uuid, "spool-001")
        self.assertEqual(rows[0].material_subtype, "PolyTerra")
        self.assertEqual(rows[0].color_name, "Charcoal Black")
        self.assertEqual(rows[0].remaining_weight, 750)
        self.assertEqual(rows[0].purchase_price, 19.99)
        self.assertEqual(rows[0].purchase_date, "2026-01-15")
        self.assertEqual(rows[0].nozzle_temperature, 210)
        self.assertEqual(rows[0].bed_temperature, 60)
        self.assertEqual(rows[0].empty_spool_weight, 140)
        self.assertEqual(rows[0].purchase_notes, "Sale purchase")
        self.assertEqual(rows[0].purchase_currency, "GBP")
        self.assertEqual(rows[0].spool_url, "https://example.test/spools/spool-001")
        self.assertEqual(rows[0].filament_url, "https://example.test/filaments/polyterra-charcoal")
        self.assertEqual(rows[0].updated_at, "2026-04-01T10:00:00Z")
        self.assertEqual(rows[0].td_value, "0.030")
        self.assertEqual(rows[0].spool_td_value, "0.031")
        self.assertEqual(rows[0].spool_k_value, "0.020")
        self.assertEqual(rows[0].spool_flow_ratio, "0.98")

    def test_dry_run_reports_planned_work_without_writes_or_backup(self) -> None:
        client = FakeSpoolmanClient()
        report = ThreeDfpImporter(client).dry_run(FIXTURE)

        self.assertTrue(report.dry_run)
        self.assertEqual(report.rows_seen, 4)
        self.assertEqual(report.rows_valid, 3)
        self.assertEqual(report.vendors_created, 2)
        self.assertEqual(report.filaments_created, 3)
        self.assertEqual(report.spools_created, 3)
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(client.backups_created, 0)
        self.assertEqual(client.created_vendors, [])
        self.assertEqual(client.created_filaments, [])
        self.assertEqual(client.created_spools, [])
        self.assertIsNotNone(report.start_time)
        self.assertIsNotNone(report.finish_time)
        self.assertGreaterEqual(report.duration_seconds, 0)
        self.assertEqual(report.source_csv_path, str(FIXTURE))
        self.assertIsNone(report.json_report_path)
        self.assertIsNone(report.txt_report_path)

    def test_apply_creates_backup_then_vendors_filaments_and_spools(self) -> None:
        client = FakeSpoolmanClient()
        report = ThreeDfpImporter(client).apply(FIXTURE)

        self.assertFalse(report.dry_run)
        self.assertEqual(report.backup_path, "/backups/spoolman.db")
        self.assertEqual(client.backups_created, 1)
        self.assertEqual([request.name for request in client.created_vendors], ["Polymaker", "Prusament"])
        self.assertEqual(len(client.created_filaments), 3)
        self.assertEqual(len(client.created_spools), 3)

        first_filament = client.created_filaments[0]
        self.assertEqual(first_filament.name, "PolyTerra Charcoal Black")
        self.assertEqual(first_filament.material, "PLA")
        self.assertEqual(first_filament.color_hex, "222222")
        self.assertEqual(first_filament.settings_extruder_temp, 210)
        self.assertEqual(first_filament.settings_bed_temp, 60)
        self.assertEqual(first_filament.spool_weight, 140)
        self.assertEqual(first_filament.price, 19.99)
        self.assertIsNone(first_filament.article_number)
        self.assertIsNone(first_filament.external_id)
        self.assertIsNone(getattr(first_filament, "extra", None))
        self.assertIn("Material subtype: PolyTerra", first_filament.comment or "")
        self.assertIn("Colour name: Charcoal Black", first_filament.comment or "")

        second_filament = client.created_filaments[1]
        self.assertIsNone(second_filament.color_hex)
        self.assertEqual(second_filament.multi_color_hexes, "FF0000,00FF00")
        self.assertEqual(second_filament.multi_color_direction, "coaxial")

        first_spool = client.created_spools[0]
        self.assertEqual(first_spool.remaining_weight, 750)
        self.assertEqual(first_spool.location, "Shelf A")
        self.assertEqual(first_spool.price, 19.99)
        self.assertIn(spool_uuid_marker("spool-001"), first_spool.comment or "")
        self.assertIn("Purchase date: 2026-01-15", first_spool.comment or "")
        self.assertIn("Notes: Opened for sample prints", first_spool.comment or "")
        self.assertIn("Purchase notes: Sale purchase", first_spool.comment or "")
        self.assertIn("Purchase currency: GBP", first_spool.comment or "")
        self.assertIn("Spool URL: https://example.test/spools/spool-001", first_spool.comment or "")
        self.assertIn("Filament URL: https://example.test/filaments/polyterra-charcoal", first_spool.comment or "")
        self.assertIn("Updated at: 2026-04-01T10:00:00Z", first_spool.comment or "")
        self.assertIn("TD value: 0.030", first_spool.comment or "")
        self.assertIn("Spool TD value: 0.031", first_spool.comment or "")
        self.assertIn("Spool K value: 0.020", first_spool.comment or "")
        self.assertIn("Spool flow ratio: 0.98", first_spool.comment or "")
        self.assertIsNone(getattr(first_spool, "extra", None))

    def test_apply_reuses_existing_vendor_and_filament(self) -> None:
        vendor = Vendor(id=10, registered="2026-07-16T12:00:00Z", name="Polymaker", extra={})
        filament = Filament(
            id=20,
            registered="2026-07-16T12:00:00Z",
            density=1.24,
            diameter=1.75,
            name="PolyTerra Charcoal Black",
            vendor=vendor,
            material="PLA",
            color_hex="222222",
            extra={},
        )
        client = FakeSpoolmanClient(vendors=[vendor], filaments=[filament])

        report = ThreeDfpImporter(client).apply(FIXTURE)

        self.assertEqual(report.vendors_reused, 1)
        self.assertEqual(report.filaments_reused, 1)
        self.assertEqual(client.created_spools[0].filament_id, 20)

    def test_apply_skips_spool_with_existing_3dfp_marker(self) -> None:
        vendor = Vendor(id=1, registered="2026-07-16T12:00:00Z", name="Polymaker", extra={})
        filament = Filament(id=1, registered="2026-07-16T12:00:00Z", density=1.24, diameter=1.75, extra={})
        existing_spool = Spool(
            id=1,
            registered="2026-07-16T12:00:00Z",
            filament=filament,
            used_weight=0,
            used_length=0,
            archived=False,
            comment=f"{SPOOL_UUID_COMMENT_MARKER} spool-001",
            extra={},
        )
        client = FakeSpoolmanClient(vendors=[vendor], spools=[existing_spool])

        report = ThreeDfpImporter(client).apply(FIXTURE)

        self.assertEqual(report.spools_skipped, 1)
        self.assertEqual(len(client.created_spools), 2)
        self.assertTrue(any(action.action == "skip_spool" for action in report.actions))
        self.assertEqual(report.duplicate_spool_uuids, ["spool-001"])

    def test_reports_are_written_to_explicit_temporary_directory(self) -> None:
        client = FakeSpoolmanClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            report = ThreeDfpImporter(client).dry_run(FIXTURE, report_output_dir=temp_dir)
            json_path = Path(report.json_report_path or "")
            txt_path = Path(report.txt_report_path or "")

            self.assertTrue(json_path.exists())
            self.assertTrue(txt_path.exists())
            self.assertEqual(json_path.parent, Path(temp_dir))
            self.assertEqual(txt_path.parent, Path(temp_dir))

            report_data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(report_data["source_csv_path"], str(FIXTURE))
            self.assertEqual(report_data["rows_seen"], 4)
            self.assertEqual(report_data["rows_valid"], 3)
            self.assertEqual(report_data["vendors_created"], 2)
            self.assertEqual(report_data["filaments_created"], 3)
            self.assertEqual(report_data["spools_created"], 3)
            self.assertEqual(report_data["backup_path"], None)
            self.assertEqual(len(report_data["errors"]), 1)

            text_report = txt_path.read_text(encoding="utf-8")
            self.assertIn("3D Filament Profiles Import Report", text_report)
            self.assertIn("Mode: dry-run", text_report)
            self.assertIn("Rows seen: 4", text_report)
            self.assertIn("Row 5: Missing required manufacturer.", text_report)

    def test_apply_report_includes_backup_path_and_duplicate_uuids(self) -> None:
        vendor = Vendor(id=1, registered="2026-07-16T12:00:00Z", name="Polymaker", extra={})
        filament = Filament(id=1, registered="2026-07-16T12:00:00Z", density=1.24, diameter=1.75, extra={})
        existing_spool = Spool(
            id=1,
            registered="2026-07-16T12:00:00Z",
            filament=filament,
            used_weight=0,
            used_length=0,
            archived=False,
            comment=f"{SPOOL_UUID_COMMENT_MARKER} spool-001",
            extra={},
        )
        client = FakeSpoolmanClient(vendors=[vendor], spools=[existing_spool])

        with tempfile.TemporaryDirectory() as temp_dir:
            report = ThreeDfpImporter(client).apply(FIXTURE, report_output_dir=temp_dir)
            report_data = json.loads(Path(report.json_report_path or "").read_text(encoding="utf-8"))

        self.assertEqual(report.backup_path, "/backups/spoolman.db")
        self.assertEqual(report.duplicate_spool_uuids, ["spool-001"])
        self.assertEqual(report_data["backup_path"], "/backups/spoolman.db")
        self.assertEqual(report_data["duplicate_spool_uuids"], ["spool-001"])

    def test_cli_uses_default_report_dir_and_spoolman_url_override(self) -> None:
        with patch("app.importers.three_dfp.SpoolmanClient") as client_class:
            with patch("app.importers.three_dfp.ThreeDfpImporter") as importer_class:
                importer = importer_class.return_value
                importer.import_csv.return_value = type(
                    "Report",
                    (),
                    {
                        "dry_run": True,
                        "rows_seen": 4,
                        "rows_valid": 3,
                        "errors": [],
                        "json_report_path": "import_reports/report.json",
                        "txt_report_path": "import_reports/report.txt",
                    },
                )()

                with redirect_stdout(StringIO()):
                    exit_code = main(
                        [
                            str(FIXTURE),
                            "--dry-run",
                            "--spoolman-url",
                            "http://spoolman.local:7912",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        client_class.assert_called_once_with(base_url="http://spoolman.local:7912")
        importer.import_csv.assert_called_once_with(str(FIXTURE), apply=False, report_output_dir="import_reports")


if __name__ == "__main__":
    unittest.main()
