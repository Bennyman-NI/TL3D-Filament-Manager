from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.spoolman_client import (
    ApiInfo,
    BackupResponse,
    CreateFilamentRequest,
    CreateSpoolRequest,
    CreateVendorRequest,
    Filament,
    HealthCheck,
    Spool,
    SpoolmanClient,
    SpoolmanConnectionError,
    SpoolmanHTTPError,
    SpoolmanValidationError,
    Vendor,
)


class FakeResponse:
    def __init__(self, payload: object, status: int = 200, reason: str = "OK") -> None:
        self.status = status
        self.reason = reason
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body


class RawFakeResponse(FakeResponse):
    def __init__(self, body: bytes, status: int = 200, reason: str = "OK") -> None:
        self.status = status
        self.reason = reason
        self._body = body


class SpoolmanClientTests(unittest.TestCase):
    def test_health_check_uses_api_v1_root(self) -> None:
        with patch("app.spoolman_client.urlopen", return_value=FakeResponse({"status": "healthy"})) as urlopen_mock:
            result = SpoolmanClient().health_check()

        self.assertEqual(result, HealthCheck(status="healthy"))
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:7912/api/v1/health")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(urlopen_mock.call_args.kwargs["timeout"], 10.0)

    def test_api_info_returns_typed_result(self) -> None:
        payload = {
            "version": "0.24.0",
            "debug_mode": False,
            "automatic_backups": True,
            "data_dir": "/data",
            "logs_dir": "/logs",
            "backups_dir": "/backups",
            "db_type": "sqlite",
            "git_commit": "103e029",
            "build_date": "2026-07-07T09:58:13Z",
        }

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(payload)):
            result = SpoolmanClient("http://spoolman.local/").api_info()

        self.assertEqual(
            result,
            ApiInfo(
                version="0.24.0",
                debug_mode=False,
                automatic_backups=True,
                data_dir="/data",
                logs_dir="/logs",
                backups_dir="/backups",
                db_type="sqlite",
                git_commit="103e029",
                build_date="2026-07-07T09:58:13Z",
            ),
        )

    def test_list_vendors_returns_typed_results_and_query_params(self) -> None:
        payload = [
            {
                "id": 1,
                "registered": "2026-07-16T12:00:00Z",
                "name": "Polymaker",
                "comment": None,
                "empty_spool_weight": 140,
                "external_id": "polymaker",
                "extra": {"source": "test"},
            }
        ]

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(payload)) as urlopen_mock:
            result = SpoolmanClient().list_vendors(name="poly", sort="name:asc", limit=10)

        self.assertEqual(
            result,
            [
                Vendor(
                    id=1,
                    registered="2026-07-16T12:00:00Z",
                    name="Polymaker",
                    empty_spool_weight=140.0,
                    external_id="polymaker",
                    extra={"source": "test"},
                )
            ],
        )
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://localhost:7912/api/v1/vendor?name=poly&sort=name%3Aasc&limit=10&offset=0",
        )

    def test_list_filaments_parses_nested_vendor(self) -> None:
        payload = [
            {
                "id": 2,
                "registered": "2026-07-16T12:00:00Z",
                "name": "Charcoal Black",
                "vendor": {"id": 1, "registered": "2026-07-16T12:00:00Z", "name": "Polymaker", "extra": {}},
                "material": "PLA",
                "density": 1.24,
                "diameter": 1.75,
                "extra": {},
            }
        ]

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(payload)):
            result = SpoolmanClient().list_filaments()

        self.assertIsInstance(result[0], Filament)
        self.assertEqual(result[0].vendor, Vendor(id=1, registered="2026-07-16T12:00:00Z", name="Polymaker", extra={}))
        self.assertEqual(result[0].material, "PLA")

    def test_list_spools_parses_nested_filament_and_bool_query(self) -> None:
        payload = [
            {
                "id": 3,
                "registered": "2026-07-16T12:00:00Z",
                "filament": {
                    "id": 2,
                    "registered": "2026-07-16T12:00:00Z",
                    "density": 1.24,
                    "diameter": 1.75,
                    "extra": {},
                },
                "used_weight": 42.5,
                "used_length": 1200.0,
                "archived": False,
                "extra": {},
            }
        ]

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(payload)) as urlopen_mock:
            result = SpoolmanClient().list_spools(allow_archived=True)

        self.assertIsInstance(result[0], Spool)
        self.assertEqual(result[0].filament.id, 2)
        self.assertEqual(result[0].used_weight, 42.5)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:7912/api/v1/spool?allow_archived=true&offset=0")

    def test_create_backup_returns_typed_result(self) -> None:
        with patch("app.spoolman_client.urlopen", return_value=FakeResponse({"path": "/backups/spoolman.db"})) as mock:
            result = SpoolmanClient(timeout=3.0).create_backup()

        self.assertEqual(result, BackupResponse(path="/backups/spoolman.db"))
        request = mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:7912/api/v1/backup")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(mock.call_args.kwargs["timeout"], 3.0)

    def test_create_vendor_sends_supported_json_body(self) -> None:
        response = {
            "id": 1,
            "registered": "2026-07-16T12:00:00Z",
            "name": "Polymaker",
            "comment": "imported",
            "extra": {},
        }

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(response)) as mock:
            result = SpoolmanClient().create_vendor(CreateVendorRequest(name="Polymaker", comment="imported"))

        self.assertEqual(result.name, "Polymaker")
        request = mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:7912/api/v1/vendor")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"name": "Polymaker", "comment": "imported"})

    def test_create_filament_sends_only_non_none_supported_fields(self) -> None:
        response = {
            "id": 2,
            "registered": "2026-07-16T12:00:00Z",
            "name": "Galaxy PLA",
            "vendor": {"id": 1, "registered": "2026-07-16T12:00:00Z", "name": "Polymaker", "extra": {}},
            "material": "PLA",
            "density": 1.24,
            "diameter": 1.75,
            "color_hex": "112233",
            "settings_extruder_temp": 215,
            "settings_bed_temp": 60,
            "extra": {},
        }
        create_request = CreateFilamentRequest(
            name="Galaxy PLA",
            vendor_id=1,
            material="PLA",
            density=1.24,
            diameter=1.75,
            color_hex="112233",
            multi_color_hexes=None,
            multi_color_direction=None,
            settings_extruder_temp=215,
            settings_bed_temp=60,
            weight=1000,
            spool_weight=140,
            price=22.5,
            article_number="PM70123",
            comment="profile import",
            external_id="poly_galaxy_pla",
        )

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(response)) as mock:
            result = SpoolmanClient().create_filament(create_request)

        self.assertEqual(result.id, 2)
        body = json.loads(mock.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "density": 1.24,
                "diameter": 1.75,
                "name": "Galaxy PLA",
                "vendor_id": 1,
                "material": "PLA",
                "price": 22.5,
                "weight": 1000,
                "spool_weight": 140,
                "article_number": "PM70123",
                "comment": "profile import",
                "settings_extruder_temp": 215,
                "settings_bed_temp": 60,
                "color_hex": "112233",
                "external_id": "poly_galaxy_pla",
            },
        )
        self.assertNotIn("extra", body)
        self.assertNotIn("multi_color_hexes", body)

    def test_create_filament_supports_multicolor_values(self) -> None:
        response = {
            "id": 2,
            "registered": "2026-07-16T12:00:00Z",
            "density": 1.24,
            "diameter": 1.75,
            "multi_color_hexes": "FF0000,00FF00",
            "multi_color_direction": "coaxial",
            "extra": {},
        }

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(response)) as mock:
            SpoolmanClient().create_filament(
                CreateFilamentRequest(
                    density=1.24,
                    diameter=1.75,
                    multi_color_hexes="FF0000,00FF00",
                    multi_color_direction="coaxial",
                )
            )

        body = json.loads(mock.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(body["multi_color_hexes"], "FF0000,00FF00")
        self.assertEqual(body["multi_color_direction"], "coaxial")
        self.assertNotIn("color_hex", body)

    def test_create_spool_sends_only_non_none_supported_fields(self) -> None:
        response = {
            "id": 3,
            "registered": "2026-07-16T12:00:00Z",
            "filament": {
                "id": 2,
                "registered": "2026-07-16T12:00:00Z",
                "density": 1.24,
                "diameter": 1.75,
                "extra": {},
            },
            "used_weight": 0,
            "used_length": 0,
            "archived": True,
            "extra": {},
        }

        with patch("app.spoolman_client.urlopen", return_value=FakeResponse(response)) as mock:
            result = SpoolmanClient().create_spool(
                CreateSpoolRequest(
                    filament_id=2,
                    initial_weight=1000,
                    remaining_weight=800,
                    spool_weight=140,
                    price=22.5,
                    location="Shelf A",
                    lot_nr="LOT-42",
                    comment="profile import",
                    archived=True,
                )
            )

        self.assertEqual(result.id, 3)
        body = json.loads(mock.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "filament_id": 2,
                "price": 22.5,
                "initial_weight": 1000,
                "spool_weight": 140,
                "remaining_weight": 800,
                "location": "Shelf A",
                "lot_nr": "LOT-42",
                "comment": "profile import",
                "archived": True,
            },
        )
        self.assertNotIn("extra", body)

    def test_connection_errors_are_wrapped(self) -> None:
        with patch("app.spoolman_client.urlopen", side_effect=URLError("refused")):
            with self.assertRaises(SpoolmanConnectionError):
                SpoolmanClient().health_check()

    def test_http_errors_are_wrapped_with_status_and_body(self) -> None:
        http_error = HTTPError(
            url="http://localhost:7912/api/v1/backup",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=BytesIO(b'{"message":"Backup failed"}'),
        )

        with patch("app.spoolman_client.urlopen", side_effect=http_error):
            with self.assertRaises(SpoolmanHTTPError) as raised:
                SpoolmanClient().create_backup()

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("Backup failed", raised.exception.body)

    def test_http_400_errors_are_wrapped_for_create_vendor(self) -> None:
        http_error = HTTPError(
            url="http://localhost:7912/api/v1/vendor",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"message":"Vendor already exists"}'),
        )

        with patch("app.spoolman_client.urlopen", side_effect=http_error):
            with self.assertRaises(SpoolmanHTTPError) as raised:
                SpoolmanClient().create_vendor(CreateVendorRequest(name="Polymaker"))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Vendor already exists", raised.exception.body)

    def test_http_422_errors_are_wrapped_for_create_filament(self) -> None:
        http_error = HTTPError(
            url="http://localhost:7912/api/v1/filament",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=BytesIO(b'{"detail":[{"msg":"Input should be greater than 0"}]}'),
        )

        with patch("app.spoolman_client.urlopen", side_effect=http_error):
            with self.assertRaises(SpoolmanHTTPError) as raised:
                SpoolmanClient().create_filament(CreateFilamentRequest(density=0, diameter=1.75))

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("greater than 0", raised.exception.body)

    def test_invalid_json_raises_validation_error(self) -> None:
        with patch("app.spoolman_client.urlopen", return_value=RawFakeResponse(b"not json")):
            with self.assertRaises(SpoolmanValidationError):
                SpoolmanClient().health_check()

    def test_missing_required_field_raises_validation_error(self) -> None:
        with patch("app.spoolman_client.urlopen", return_value=FakeResponse({"not_status": "healthy"})):
            with self.assertRaises(SpoolmanValidationError):
                SpoolmanClient().health_check()


if __name__ == "__main__":
    unittest.main()
