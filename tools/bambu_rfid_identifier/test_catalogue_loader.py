from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

import catalogue_loader
import update_catalogue


class CatalogueUpdaterTests(unittest.TestCase):
    def test_successful_initial_download_writes_cache_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = update_catalogue.update_catalogue(cache_dir=cache_dir, urlopen=StaticHttp(sample_catalogue()).urlopen)

            self.assertEqual(result.status, "updated")
            self.assertEqual(result.added, 2)
            self.assertTrue((cache_dir / "filaments.json").exists())
            metadata = json.loads((cache_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_repository"], "piitaya/bambu-filaments")
            self.assertEqual(metadata["record_count"], 2)
            self.assertEqual(metadata["sha256"], result.checksum)
            self.assertEqual(metadata["etag"], '"abc"')
            self.assertEqual(metadata["last_modified"], "Fri, 24 Jul 2026 10:00:00 GMT")

    def test_http_304_reports_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            write_metadata(cache_dir, {"record_count": 2, "sha256": "old", "etag": '"abc"', "last_modified": "yesterday"})

            result = update_catalogue.update_catalogue(cache_dir=cache_dir, urlopen=NotModifiedHttp().urlopen)

            self.assertEqual(result.status, "up_to_date")
            self.assertEqual(result.record_count, 2)

    def test_forced_update_skips_conditional_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            write_metadata(cache_dir, {"etag": '"abc"', "last_modified": "yesterday"})
            http = StaticHttp(sample_catalogue())

            update_catalogue.update_catalogue(force=True, cache_dir=cache_dir, urlopen=http.urlopen)

            self.assertNotIn("If-none-match", http.headers)
            self.assertNotIn("If-modified-since", http.headers)

    def test_dry_run_makes_no_filesystem_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)

            result = update_catalogue.update_catalogue(dry_run=True, cache_dir=cache_dir, urlopen=StaticHttp(sample_catalogue()).urlopen)

            self.assertEqual(result.status, "updated")
            self.assertFalse((cache_dir / "filaments.json").exists())
            self.assertFalse((cache_dir / "metadata.json").exists())

    def test_invalid_json_keeps_previous_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            write_cache(cache_dir, sample_catalogue())

            result = update_catalogue.update_catalogue(cache_dir=cache_dir, urlopen=StaticHttp(b"{bad").urlopen)

            self.assertEqual(result.status, "error")
            self.assertEqual(json.loads((cache_dir / "filaments.json").read_text(encoding="utf-8"))[0]["id"], "A00-A1")

    def test_invalid_schema_rejects_complete_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = update_catalogue.update_catalogue(cache_dir=Path(temp_dir), urlopen=StaticHttp(json_bytes([{"id": ""}])).urlopen)

            self.assertEqual(result.status, "error")
            self.assertIn("non-empty string", result.error or "")

    def test_duplicate_variant_ids_reject_complete_update(self) -> None:
        duplicate = [record("A00-A1"), record("A00-A1")]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = update_catalogue.update_catalogue(cache_dir=Path(temp_dir), urlopen=StaticHttp(json_bytes(duplicate)).urlopen)

            self.assertEqual(result.status, "error")
            self.assertIn("duplicate variant id", result.error or "")

    def test_invalid_colour_hex_rejects_complete_update(self) -> None:
        bad = [record("A00-A1", color_hex="ff9016ff")]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = update_catalogue.update_catalogue(cache_dir=Path(temp_dir), urlopen=StaticHttp(json_bytes(bad)).urlopen)

            self.assertEqual(result.status, "error")
            self.assertIn("RRGGBBAA", result.error or "")

    def test_network_failure_keeps_previous_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            write_cache(cache_dir, sample_catalogue())

            result = update_catalogue.update_catalogue(cache_dir=cache_dir, urlopen=NetworkFailureHttp().urlopen)

            self.assertEqual(result.status, "error")
            self.assertTrue((cache_dir / "filaments.json").exists())

    def test_atomic_replacement_leaves_no_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)

            update_catalogue.update_catalogue(cache_dir=cache_dir, urlopen=StaticHttp(sample_catalogue()).urlopen)

            self.assertEqual(list(cache_dir.glob("*.tmp")), [])

    def test_added_changed_removed_unchanged_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            write_cache(cache_dir, json_bytes([record("A00-A1"), record("OLD-ID")]))
            new = json_bytes([record("A00-A1"), record("G02-K0", product="PETG HF"), record("A00-B9", color_name="Blue")])

            result = update_catalogue.update_catalogue(cache_dir=cache_dir, urlopen=StaticHttp(new).urlopen)

            self.assertEqual(result.added, 2)
            self.assertEqual(result.changed, 0)
            self.assertEqual(result.removed, 1)
            self.assertEqual(result.unchanged, 1)

    def test_json_cli_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = update_catalogue.main(["--json"], cache_dir=Path(temp_dir), urlopen=StaticHttp(sample_catalogue()).urlopen)

            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "updated")
            self.assertEqual(payload["record_count"], 2)

    def test_metadata_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)

            update_catalogue.update_catalogue(cache_dir=cache_dir, urlopen=StaticHttp(sample_catalogue()).urlopen)
            metadata = json.loads((cache_dir / "metadata.json").read_text(encoding="utf-8"))

            self.assertEqual(metadata["local_schema_version"], 1)
            self.assertEqual(metadata["source_url"], catalogue_loader.SOURCE_URL)
            self.assertTrue(metadata["fetched_at_utc"].endswith("Z"))


class CatalogueResolverTests(unittest.TestCase):
    def test_exact_matches_from_cache(self) -> None:
        with temporary_cache(sample_catalogue()) as cache_dir:
            match = resolve_with_cache(cache_dir, "A00-A1", "PLA", "PLA Basic", "FF9016FF")

        self.assertEqual(match.status, "exact")
        self.assertEqual(match.catalogue_name, "Bambu Lab PLA Basic Pumpkin Orange")
        self.assertEqual(match.source, "piitaya/bambu-filaments cache")
        self.assertEqual(match.entry_id, "A00-A1")

    def test_exact_pla_basic_blue_and_petg_hf_black(self) -> None:
        catalogue = json_bytes([record("A00-B9", color_name="Blue", color_hex="0A2989FF"), record("G02-K0", material="PETG", product="PETG HF", color_name="Black", color_hex="000000FF")])
        with temporary_cache(catalogue) as cache_dir:
            blue = resolve_with_cache(cache_dir, "A00-B9", "PLA", "PLA Basic", "0A2989FF")
            black = resolve_with_cache(cache_dir, "G02-K0", "PETG", "PETG HF", "000000FF")

        self.assertEqual(blue.catalogue_name, "Bambu Lab PLA Basic Blue")
        self.assertEqual(black.catalogue_name, "Bambu Lab PETG HF Black")

    def test_unknown_variant(self) -> None:
        with temporary_cache(sample_catalogue()) as cache_dir:
            match = resolve_with_cache(cache_dir, "NOPE", "PLA", "PLA Basic", "FF9016FF")

        self.assertEqual(match.status, "unknown")
        self.assertIsNone(match.catalogue_name)

    def test_product_material_and_colour_mismatch_warnings(self) -> None:
        with temporary_cache(sample_catalogue()) as cache_dir:
            match = resolve_with_cache(cache_dir, "A00-A1", "PETG", "PLA Matte", "000000FF")

        self.assertEqual(match.status, "identifier_match_with_warning")
        self.assertTrue(any("material" in warning for warning in match.validation_warnings))
        self.assertTrue(any("product" in warning for warning in match.validation_warnings))
        self.assertTrue(any("RGBA" in warning for warning in match.validation_warnings))

    def test_fallback_catalogue_match_when_no_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            match = catalogue_loader.resolve_catalogue_with_cache(fields("A00-A1", "PLA", "PLA Basic", "FF9016FF"), Path(temp_dir))

        self.assertEqual(match.status, "exact")
        self.assertEqual(match.source, "bundled validated fallback")
        self.assertEqual(match.catalogue_name, "Bambu Lab PLA Basic Pumpkin Orange")

    def test_cache_fallback_conflict_is_reported(self) -> None:
        conflicting = json_bytes([record("A00-A1", color_name="Generic Orange")])
        with temporary_cache(conflicting) as cache_dir:
            match = resolve_with_cache(cache_dir, "A00-A1", "PLA", "PLA Basic", "FF9016FF")

        self.assertEqual(match.status, "identifier_match_with_warning")
        self.assertTrue(any("conflicts with bundled" in warning for warning in match.validation_warnings))

    def test_provenance_fields_are_reported(self) -> None:
        with temporary_cache(sample_catalogue()) as cache_dir:
            match = resolve_with_cache(cache_dir, "A00-A1", "PLA", "PLA Basic", "FF9016FF")

        self.assertEqual(match.source_repository, "piitaya/bambu-filaments")
        self.assertIsNotNone(match.source_checksum)
        self.assertEqual(match.source_fetched_at, "2026-07-24T10:00:00Z")


class StaticHttp:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers: dict[str, str] = {}

    def urlopen(self, request, timeout: int | None = None):
        self.headers = dict(request.header_items())
        return FakeResponse(self.body)


class NotModifiedHttp:
    def urlopen(self, request, timeout: int | None = None):
        raise urllib.error.HTTPError(request.full_url, 304, "Not Modified", None, None)


class NetworkFailureHttp:
    def urlopen(self, request, timeout: int | None = None):
        raise OSError("network down")


class FakeResponse:
    status = 200
    headers = {"ETag": '"abc"', "Last-Modified": "Fri, 24 Jul 2026 10:00:00 GMT"}

    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body


def sample_catalogue() -> bytes:
    return json_bytes([record("A00-A1"), record("G02-K0", material="PETG", product="PETG HF", color_name="Black", color_hex="000000FF")])


def record(
    variant_id: str,
    material: str | None = "PLA",
    product: str | None = "PLA Basic",
    color_name: str | None = "Pumpkin Orange",
    color_hex: str | None = "FF9016FF",
) -> dict[str, object]:
    return {
        "id": variant_id,
        "sku": "12345",
        "material": material,
        "product": product,
        "color_name": color_name,
        "color_hex": color_hex,
        "color_hexes": [color_hex] if color_hex else [],
        "weight": 1000,
        "temp_min": 190,
        "temp_max": 230,
        "integrations": {"spoolman": "example"},
    }


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


def write_cache(cache_dir: Path, raw: bytes) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "filaments.json").write_bytes(raw)


def write_metadata(cache_dir: Path, metadata: dict[str, object]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


@contextlib.contextmanager
def temporary_cache(raw: bytes):
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = Path(temp_dir)
        write_cache(cache_dir, raw)
        write_metadata(
            cache_dir,
            {
                "source_repository": "piitaya/bambu-filaments",
                "sha256": catalogue_loader.sha256_hex(raw),
                "fetched_at_utc": "2026-07-24T10:00:00Z",
                "record_count": len(json.loads(raw.decode("utf-8"))),
            },
        )
        yield cache_dir


def resolve_with_cache(cache_dir: Path, variant_id: str, material: str, product: str, color_hex: str):
    return catalogue_loader.resolve_catalogue_with_cache(fields(variant_id, material, product, color_hex), cache_dir)


def fields(variant_id: str, material: str, product: str, color_hex: str) -> dict[str, object]:
    return {
        "tray_info_variant_id": variant_id,
        "filament_type": material,
        "detailed_filament_type": product,
        "color_rgba": {"hex": color_hex},
    }


if __name__ == "__main__":
    unittest.main()
