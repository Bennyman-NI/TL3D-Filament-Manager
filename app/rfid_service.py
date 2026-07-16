from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from app.spoolman_client import DEFAULT_BASE_URL, Filament, Spool, SpoolmanClient, SpoolmanClientError

DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_PORT = 8123
INVENTORY_FETCH_LIMIT = 10000
MATCH_PATH = "/api/rfid/match"


class SpoolmanReader(Protocol):
    def list_filaments(self, *, sort: str | None = None, limit: int | None = None, offset: int = 0) -> list[Filament]:
        ...

    def list_spools(
        self,
        *,
        allow_archived: bool = False,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Spool]:
        ...


@dataclass(frozen=True)
class RfidMatchRequest:
    manufacturer: str
    material: str
    variant: str
    colors: tuple[str, ...]


@dataclass(frozen=True)
class FilamentCandidate:
    filament_id: int
    name: str | None
    vendor: str | None
    material: str | None
    color_hex: str | None
    multi_color_hexes: str | None


@dataclass(frozen=True)
class MatchingSpool:
    spool_id: int
    remaining_weight: float | None
    location: str | None


@dataclass(frozen=True)
class RfidMatchResult:
    matched: bool
    status: str
    reason: str
    filament_id: int | None = None
    filament_name: str | None = None
    vendor: str | None = None
    material: str | None = None
    color_hex: str | None = None
    multi_color_hexes: str | None = None
    spools: tuple[MatchingSpool, ...] = ()
    candidates: tuple[FilamentCandidate, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None and (key not in {"spools", "candidates"} or value)
        }


def match_rfid_filament(client: SpoolmanReader, payload: dict[str, Any]) -> RfidMatchResult:
    request = parse_rfid_match_request(payload)
    filaments = client.list_filaments(limit=INVENTORY_FETCH_LIMIT)
    candidates = _filter_filaments(filaments, request)

    if not candidates:
        return RfidMatchResult(
            matched=False,
            status="not_found",
            reason="No filament matched vendor, material, variant, and colour.",
        )

    candidate_results = tuple(_filament_candidate(filament) for filament in candidates)
    if len(candidates) > 1:
        return RfidMatchResult(
            matched=False,
            status="ambiguous",
            reason="Multiple filaments matched vendor, material, variant, and colour.",
            candidates=candidate_results,
        )

    filament = candidates[0]
    spools = tuple(
        MatchingSpool(spool_id=spool.id, remaining_weight=spool.remaining_weight, location=spool.location)
        for spool in client.list_spools(limit=INVENTORY_FETCH_LIMIT, allow_archived=False)
        if spool.filament.id == filament.id
    )
    vendor_name = filament.vendor.name if filament.vendor is not None else None
    return RfidMatchResult(
        matched=True,
        status="matched",
        reason="Matched exactly by vendor, material, variant, and colour.",
        filament_id=filament.id,
        filament_name=filament.name,
        vendor=vendor_name,
        material=filament.material,
        color_hex=_normalise_hex_value(filament.color_hex) if filament.color_hex else None,
        multi_color_hexes=_normalise_multi_hexes(filament.multi_color_hexes)
        if filament.multi_color_hexes
        else None,
        spools=spools,
    )


def parse_rfid_match_request(payload: dict[str, Any]) -> RfidMatchRequest:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    manufacturer = _required_string(payload, "manufacturer")
    material = _required_string(payload, "material")
    variant = _required_string(payload, "variant")
    colors_value = payload.get("colors")
    if not isinstance(colors_value, list) or not colors_value:
        raise ValueError("'colors' must be a non-empty array of hex colour values.")

    colors: list[str] = []
    for item in colors_value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("'colors' must contain only non-empty strings.")
        colors.extend(_normalise_hex_value(color) for color in _split_hex_values(item))
    if not colors:
        raise ValueError("'colors' must contain at least one hex colour value.")

    return RfidMatchRequest(
        manufacturer=manufacturer,
        material=material,
        variant=variant,
        colors=tuple(colors),
    )


def make_handler(client: SpoolmanReader) -> type[BaseHTTPRequestHandler]:
    class RfidRequestHandler(BaseHTTPRequestHandler):
        server_version = "TL3DRfidService/1.0"

        def do_POST(self) -> None:
            if self.path != MATCH_PATH:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
                return

            try:
                body = self.rfile.read(_content_length(self.headers.get("Content-Length")))
                payload = json.loads(body.decode("utf-8"))
                result = match_rfid_filament(client, payload)
            except json.JSONDecodeError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {exc.msg}."})
                return
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except SpoolmanClientError as exc:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
                return

            self._send_json(HTTPStatus.OK, result.to_json_dict())

        def do_GET(self) -> None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return RfidRequestHandler


def run_server(
    *,
    spoolman_url: str = DEFAULT_BASE_URL,
    host: str = DEFAULT_BIND_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    client = SpoolmanClient(spoolman_url)
    server = ThreadingHTTPServer((host, port), make_handler(client))
    print(f"RFID matching service listening on http://{host}:{port}")
    print(f"Using Spoolman at {spoolman_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping RFID matching service")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the TL3D local RFID matching service.")
    parser.add_argument("--spoolman-url", default=DEFAULT_BASE_URL, help="Spoolman base URL.")
    parser.add_argument("--host", default=DEFAULT_BIND_HOST, help="Bind host.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Bind port.")
    args = parser.parse_args(argv)

    run_server(spoolman_url=args.spoolman_url, host=args.host, port=args.port)
    return 0


def _filter_filaments(filaments: list[Filament], request: RfidMatchRequest) -> list[Filament]:
    return [
        filament
        for filament in filaments
        if _matches_vendor(filament, request.manufacturer)
        and _matches_text(filament.material, request.material)
        and _contains_text(filament.name, request.variant)
        and _matches_colour(filament, request.colors)
    ]


def _matches_vendor(filament: Filament, manufacturer: str) -> bool:
    if filament.vendor is None:
        return False
    return _matches_text(filament.vendor.name, manufacturer)


def _matches_text(actual: str | None, expected: str) -> bool:
    return actual is not None and actual.strip().casefold() == expected.strip().casefold()


def _contains_text(actual: str | None, expected: str) -> bool:
    return actual is not None and expected.strip().casefold() in actual.casefold()


def _matches_colour(filament: Filament, requested_colors: tuple[str, ...]) -> bool:
    requested = _normalise_color_sequence(requested_colors)
    if len(requested) == 1 and filament.color_hex is not None:
        return _normalise_hex_value(filament.color_hex) == requested[0]
    if filament.multi_color_hexes is None:
        return False
    return _normalise_multi_hexes(filament.multi_color_hexes) == ",".join(requested)


def _filament_candidate(filament: Filament) -> FilamentCandidate:
    vendor_name = filament.vendor.name if filament.vendor is not None else None
    return FilamentCandidate(
        filament_id=filament.id,
        name=filament.name,
        vendor=vendor_name,
        material=filament.material,
        color_hex=_normalise_hex_value(filament.color_hex) if filament.color_hex else None,
        multi_color_hexes=_normalise_multi_hexes(filament.multi_color_hexes) if filament.multi_color_hexes else None,
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' must be a non-empty string.")
    return value.strip()


def _content_length(value: str | None) -> int:
    try:
        length = int(value or "0")
    except ValueError as exc:
        raise ValueError("'Content-Length' must be an integer.") from exc
    if length <= 0:
        raise ValueError("Request body is required.")
    return length


def _normalise_color_sequence(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_normalise_hex_value(value) for value in values)


def _normalise_multi_hexes(value: str) -> str:
    return ",".join(_normalise_hex_value(item) for item in _split_hex_values(value))


def _split_hex_values(value: str) -> list[str]:
    return [item for item in (part.strip() for part in value.split(",")) if item]


def _normalise_hex_value(value: str) -> str:
    return value.strip().removeprefix("#").upper()


if __name__ == "__main__":
    raise SystemExit(main())
