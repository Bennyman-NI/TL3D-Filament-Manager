from __future__ import annotations

import unittest
from pathlib import Path

from app.importers.three_dfp import SPOOL_UUID_COMMENT_MARKER, ThreeDfpImporter, parse_csv, spool_uuid_marker
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
        self.assertEqual(first_filament.weight, 1000)
        self.assertEqual(first_filament.spool_weight, 140)
        self.assertEqual(first_filament.price, 19.99)
        self.assertEqual(first_filament.article_number, "PM70123")
        self.assertEqual(first_filament.external_id, "polyterra-charcoal")
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
            article_number="PM70123",
            external_id="polyterra-charcoal",
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


if __name__ == "__main__":
    unittest.main()
