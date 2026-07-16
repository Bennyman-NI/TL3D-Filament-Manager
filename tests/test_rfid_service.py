from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from app.rfid_service import MATCH_PATH, make_handler, match_rfid_filament, parse_rfid_match_request
from app.spoolman_client import Filament, Spool, Vendor


REGISTERED = "2026-07-16T12:00:00Z"


class FakeSpoolmanClient:
    def __init__(self, filaments: list[Filament], spools: list[Spool] | None = None) -> None:
        self.filaments = filaments
        self.spools = spools or []

    def list_filaments(self, *, sort: str | None = None, limit: int | None = None, offset: int = 0) -> list[Filament]:
        return self.filaments

    def list_spools(
        self,
        *,
        allow_archived: bool = False,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Spool]:
        return [spool for spool in self.spools if allow_archived or not spool.archived]


class RfidServiceTests(unittest.TestCase):
    def test_normalises_request_hex_values(self) -> None:
        request = parse_rfid_match_request(
            {
                "manufacturer": "Bambu Lab",
                "material": "PLA",
                "variant": "Basic",
                "colors": ["#0a2989"],
            }
        )

        self.assertEqual(request.colors, ("0A2989",))

    def test_pax12_basic_blue_regression_does_not_match_cobalt_blue(self) -> None:
        basic_blue = _filament(23, "Basic Blue (10601)", vendor="Bambu Lab", material="PLA", color_hex="0A2989")
        cobalt_blue = _filament(24, "Cobalt Blue", vendor="Bambu Lab", material="PLA", color_hex="0A2989")
        client = FakeSpoolmanClient(
            [cobalt_blue, basic_blue],
            spools=[
                _spool(101, basic_blue, remaining_weight=812.4, location="Shelf A"),
                _spool(102, basic_blue, remaining_weight=505, location=None),
                _spool(103, cobalt_blue, remaining_weight=990, location="Shelf B"),
            ],
        )

        result = match_rfid_filament(
            client,
            {
                "manufacturer": "Bambu Lab",
                "material": "PLA",
                "variant": "Basic",
                "nums": 1,
                "alpha": 255,
                "mode": 0,
                "colors": ["0A2989"],
            },
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.filament_id, 23)
        self.assertEqual(result.filament_name, "Basic Blue (10601)")
        self.assertEqual(result.vendor, "Bambu Lab")
        self.assertEqual(result.material, "PLA")
        self.assertEqual(result.color_hex, "0A2989")
        self.assertEqual([spool.spool_id for spool in result.spools], [101, 102])

    def test_returns_ambiguous_when_multiple_filaments_remain(self) -> None:
        client = FakeSpoolmanClient(
            [
                _filament(23, "Basic Blue (10601)", vendor="Bambu Lab", material="PLA", color_hex="0A2989"),
                _filament(25, "Basic Blue Refill", vendor="Bambu Lab", material="PLA", color_hex="0A2989"),
            ]
        )

        result = match_rfid_filament(
            client,
            {
                "manufacturer": "Bambu Lab",
                "material": "PLA",
                "variant": "Basic",
                "colors": ["#0a2989"],
            },
        )

        self.assertFalse(result.matched)
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual([candidate.filament_id for candidate in result.candidates], [23, 25])

    def test_matches_exact_multicolor_sequence(self) -> None:
        filament = _filament(
            31,
            "Rainbow PLA",
            vendor="Bambu Lab",
            material="PLA",
            multi_color_hexes="#ff0000, 00ff00,0000ff",
        )
        client = FakeSpoolmanClient([filament])

        result = match_rfid_filament(
            client,
            {
                "manufacturer": "Bambu Lab",
                "material": "PLA",
                "variant": "Rainbow",
                "colors": ["FF0000", "#00FF00", "0000ff"],
            },
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.filament_id, 31)
        self.assertEqual(result.multi_color_hexes, "FF0000,00FF00,0000FF")

    def test_http_endpoint_returns_match_json(self) -> None:
        filament = _filament(23, "Basic Blue (10601)", vendor="Bambu Lab", material="PLA", color_hex="0A2989")
        client = FakeSpoolmanClient([filament], [_spool(101, filament, remaining_weight=812.4, location="Shelf A")])
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(client))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.shutdown)

        body = json.dumps(
            {
                "manufacturer": "Bambu Lab",
                "material": "PLA",
                "variant": "Basic",
                "colors": ["0A2989"],
            }
        ).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{server.server_port}{MATCH_PATH}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["filament_id"], 23)
        self.assertEqual(payload["spools"][0]["spool_id"], 101)


def _vendor(name: str) -> Vendor:
    return Vendor(id=1, registered=REGISTERED, name=name, extra={})


def _filament(
    id: int,
    name: str,
    *,
    vendor: str,
    material: str,
    color_hex: str | None = None,
    multi_color_hexes: str | None = None,
) -> Filament:
    return Filament(
        id=id,
        registered=REGISTERED,
        density=1.24,
        diameter=1.75,
        name=name,
        vendor=_vendor(vendor),
        material=material,
        color_hex=color_hex,
        multi_color_hexes=multi_color_hexes,
        extra={},
    )


def _spool(id: int, filament: Filament, *, remaining_weight: float, location: str | None) -> Spool:
    return Spool(
        id=id,
        registered=REGISTERED,
        filament=filament,
        used_weight=0,
        used_length=0,
        archived=False,
        remaining_weight=remaining_weight,
        location=location,
        extra={},
    )


if __name__ == "__main__":
    unittest.main()
