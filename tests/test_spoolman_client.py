from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.spoolman_client import (
    ApiInfo,
    BackupResponse,
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
