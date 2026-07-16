from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://localhost:7912"
DEFAULT_TIMEOUT_SECONDS = 10.0


class SpoolmanClientError(Exception):
    """Base exception for Spoolman client failures."""


class SpoolmanConnectionError(SpoolmanClientError):
    """Raised when Spoolman cannot be reached."""


class SpoolmanHTTPError(SpoolmanClientError):
    """Raised when Spoolman returns an unsuccessful HTTP status."""

    def __init__(self, status_code: int, reason: str, body: str) -> None:
        super().__init__(f"Spoolman returned HTTP {status_code} {reason}: {body}")
        self.status_code = status_code
        self.reason = reason
        self.body = body


class SpoolmanValidationError(SpoolmanClientError):
    """Raised when Spoolman returns data that does not match the captured schema."""


@dataclass(frozen=True)
class HealthCheck:
    status: str


@dataclass(frozen=True)
class ApiInfo:
    version: str
    debug_mode: bool
    automatic_backups: bool
    data_dir: str
    logs_dir: str
    backups_dir: str
    db_type: str
    git_commit: str | None = None
    build_date: str | None = None


@dataclass(frozen=True)
class Vendor:
    id: int
    registered: str
    name: str
    comment: str | None = None
    empty_spool_weight: float | None = None
    external_id: str | None = None
    extra: dict[str, str] | None = None


@dataclass(frozen=True)
class Filament:
    id: int
    registered: str
    density: float
    diameter: float
    name: str | None = None
    vendor: Vendor | None = None
    material: str | None = None
    price: float | None = None
    weight: float | None = None
    spool_weight: float | None = None
    article_number: str | None = None
    comment: str | None = None
    settings_extruder_temp: int | None = None
    settings_bed_temp: int | None = None
    color_hex: str | None = None
    multi_color_hexes: str | None = None
    multi_color_direction: str | None = None
    external_id: str | None = None
    extra: dict[str, str] | None = None


@dataclass(frozen=True)
class Spool:
    id: int
    registered: str
    filament: Filament
    used_weight: float
    used_length: float
    archived: bool
    first_used: str | None = None
    last_used: str | None = None
    price: float | None = None
    remaining_weight: float | None = None
    initial_weight: float | None = None
    spool_weight: float | None = None
    remaining_length: float | None = None
    location: str | None = None
    lot_nr: str | None = None
    comment: str | None = None
    extra: dict[str, str] | None = None


@dataclass(frozen=True)
class BackupResponse:
    path: str


@dataclass(frozen=True)
class CreateVendorRequest:
    name: str
    comment: str | None = None


@dataclass(frozen=True)
class CreateFilamentRequest:
    density: float
    diameter: float
    name: str | None = None
    vendor_id: int | None = None
    material: str | None = None
    price: float | None = None
    weight: float | None = None
    spool_weight: float | None = None
    article_number: str | None = None
    comment: str | None = None
    settings_extruder_temp: int | None = None
    settings_bed_temp: int | None = None
    color_hex: str | None = None
    multi_color_hexes: str | None = None
    multi_color_direction: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class CreateSpoolRequest:
    filament_id: int
    price: float | None = None
    initial_weight: float | None = None
    spool_weight: float | None = None
    remaining_weight: float | None = None
    location: str | None = None
    lot_nr: str | None = None
    comment: str | None = None
    archived: bool | None = None


class SpoolmanClient:
    """Small typed client for the Spoolman REST API v1."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health_check(self) -> HealthCheck:
        return _parse_health_check(self._request_json("GET", "/health"))

    def api_info(self) -> ApiInfo:
        return _parse_api_info(self._request_json("GET", "/info"))

    def list_vendors(
        self,
        *,
        name: str | None = None,
        external_id: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Vendor]:
        payload = self._request_json(
            "GET",
            "/vendor",
            query={"name": name, "external_id": external_id, "sort": sort, "limit": limit, "offset": offset},
        )
        return _parse_list(payload, _parse_vendor, "vendor")

    def list_filaments(
        self,
        *,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Filament]:
        payload = self._request_json("GET", "/filament", query={"sort": sort, "limit": limit, "offset": offset})
        return _parse_list(payload, _parse_filament, "filament")

    def list_spools(
        self,
        *,
        allow_archived: bool = False,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Spool]:
        payload = self._request_json(
            "GET",
            "/spool",
            query={"allow_archived": allow_archived, "sort": sort, "limit": limit, "offset": offset},
        )
        return _parse_list(payload, _parse_spool, "spool")

    def create_backup(self) -> BackupResponse:
        return _parse_backup_response(self._request_json("POST", "/backup"))

    def create_vendor(self, request: CreateVendorRequest) -> Vendor:
        return _parse_vendor(self._request_json("POST", "/vendor", body=_to_request_body(request)))

    def create_filament(self, request: CreateFilamentRequest) -> Filament:
        return _parse_filament(self._request_json("POST", "/filament", body=_to_request_body(request)))

    def create_spool(self, request: CreateSpoolRequest) -> Spool:
        return _parse_spool(self._request_json("POST", "/spool", body=_to_request_body(request)))

    def _request_json(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = self._build_url(path, query)
        request_body = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if request_body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=request_body, method=method, headers=headers)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", response.getcode())
                reason = getattr(response, "reason", "")
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            exc.close()
            raise SpoolmanHTTPError(exc.code, exc.reason, body) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise SpoolmanConnectionError(f"Could not connect to Spoolman at {self.base_url}: {exc}") from exc

        if status < 200 or status >= 300:
            raise SpoolmanHTTPError(status, reason, body)

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise SpoolmanValidationError(f"Spoolman returned invalid JSON from {path}: {exc}") from exc

    def _build_url(self, path: str, query: dict[str, Any] | None) -> str:
        url = f"{self.base_url}/api/v1{path}"
        params = _clean_query(query or {})
        if params:
            url = f"{url}?{urlencode(params)}"
        return url


def _clean_query(query: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = str(value).lower()
        else:
            cleaned[key] = str(value)
    return cleaned


def _to_request_body(request: Any) -> dict[str, Any]:
    return {key: value for key, value in asdict(request).items() if value is not None}


def _parse_list(payload: Any, parser: Any, item_name: str) -> list[Any]:
    if not isinstance(payload, list):
        raise SpoolmanValidationError(f"Expected {item_name} list response, got {type(payload).__name__}.")
    return [parser(item) for item in payload]


def _require_mapping(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SpoolmanValidationError(f"Expected {name} object, got {type(payload).__name__}.")
    return payload


def _require(payload: dict[str, Any], key: str, name: str) -> Any:
    if key not in payload:
        raise SpoolmanValidationError(f"Expected {name} to include required field '{key}'.")
    return payload[key]


def _as_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SpoolmanValidationError(f"Expected '{field}' to be a string, got {type(value).__name__}.")
    return value


def _optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, field)


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SpoolmanValidationError(f"Expected '{field}' to be an integer, got bool.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SpoolmanValidationError(f"Expected '{field}' to be an integer, got {value!r}.") from exc


def _optional_int(value: Any, field: str) -> int | None:
    return None if value is None else _as_int(value, field)


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise SpoolmanValidationError(f"Expected '{field}' to be a number, got bool.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SpoolmanValidationError(f"Expected '{field}' to be a number, got {value!r}.") from exc


def _optional_float(value: Any, field: str) -> float | None:
    return None if value is None else _as_float(value, field)


def _as_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise SpoolmanValidationError(f"Expected '{field}' to be a boolean, got {type(value).__name__}.")
    return value


def _parse_health_check(payload: Any) -> HealthCheck:
    data = _require_mapping(payload, "health check")
    return HealthCheck(status=_as_str(_require(data, "status", "health check"), "status"))


def _parse_api_info(payload: Any) -> ApiInfo:
    data = _require_mapping(payload, "API info")
    return ApiInfo(
        version=_as_str(_require(data, "version", "API info"), "version"),
        debug_mode=_as_bool(_require(data, "debug_mode", "API info"), "debug_mode"),
        automatic_backups=_as_bool(_require(data, "automatic_backups", "API info"), "automatic_backups"),
        data_dir=_as_str(_require(data, "data_dir", "API info"), "data_dir"),
        logs_dir=_as_str(_require(data, "logs_dir", "API info"), "logs_dir"),
        backups_dir=_as_str(_require(data, "backups_dir", "API info"), "backups_dir"),
        db_type=_as_str(_require(data, "db_type", "API info"), "db_type"),
        git_commit=_optional_str(data.get("git_commit"), "git_commit"),
        build_date=_optional_str(data.get("build_date"), "build_date"),
    )


def _parse_vendor(payload: Any) -> Vendor:
    data = _require_mapping(payload, "vendor")
    return Vendor(
        id=_as_int(_require(data, "id", "vendor"), "id"),
        registered=_as_str(_require(data, "registered", "vendor"), "registered"),
        name=_as_str(_require(data, "name", "vendor"), "name"),
        comment=_optional_str(data.get("comment"), "comment"),
        empty_spool_weight=_optional_float(data.get("empty_spool_weight"), "empty_spool_weight"),
        external_id=_optional_str(data.get("external_id"), "external_id"),
        extra=_parse_extra(data.get("extra")),
    )


def _parse_filament(payload: Any) -> Filament:
    data = _require_mapping(payload, "filament")
    vendor_payload = data.get("vendor")
    return Filament(
        id=_as_int(_require(data, "id", "filament"), "id"),
        registered=_as_str(_require(data, "registered", "filament"), "registered"),
        density=_as_float(_require(data, "density", "filament"), "density"),
        diameter=_as_float(_require(data, "diameter", "filament"), "diameter"),
        name=_optional_str(data.get("name"), "name"),
        vendor=_parse_vendor(vendor_payload) if vendor_payload is not None else None,
        material=_optional_str(data.get("material"), "material"),
        price=_optional_float(data.get("price"), "price"),
        weight=_optional_float(data.get("weight"), "weight"),
        spool_weight=_optional_float(data.get("spool_weight"), "spool_weight"),
        article_number=_optional_str(data.get("article_number"), "article_number"),
        comment=_optional_str(data.get("comment"), "comment"),
        settings_extruder_temp=_optional_int(data.get("settings_extruder_temp"), "settings_extruder_temp"),
        settings_bed_temp=_optional_int(data.get("settings_bed_temp"), "settings_bed_temp"),
        color_hex=_optional_str(data.get("color_hex"), "color_hex"),
        multi_color_hexes=_optional_str(data.get("multi_color_hexes"), "multi_color_hexes"),
        multi_color_direction=_optional_str(data.get("multi_color_direction"), "multi_color_direction"),
        external_id=_optional_str(data.get("external_id"), "external_id"),
        extra=_parse_extra(data.get("extra")),
    )


def _parse_spool(payload: Any) -> Spool:
    data = _require_mapping(payload, "spool")
    return Spool(
        id=_as_int(_require(data, "id", "spool"), "id"),
        registered=_as_str(_require(data, "registered", "spool"), "registered"),
        filament=_parse_filament(_require(data, "filament", "spool")),
        used_weight=_as_float(_require(data, "used_weight", "spool"), "used_weight"),
        used_length=_as_float(_require(data, "used_length", "spool"), "used_length"),
        archived=_as_bool(_require(data, "archived", "spool"), "archived"),
        first_used=_optional_str(data.get("first_used"), "first_used"),
        last_used=_optional_str(data.get("last_used"), "last_used"),
        price=_optional_float(data.get("price"), "price"),
        remaining_weight=_optional_float(data.get("remaining_weight"), "remaining_weight"),
        initial_weight=_optional_float(data.get("initial_weight"), "initial_weight"),
        spool_weight=_optional_float(data.get("spool_weight"), "spool_weight"),
        remaining_length=_optional_float(data.get("remaining_length"), "remaining_length"),
        location=_optional_str(data.get("location"), "location"),
        lot_nr=_optional_str(data.get("lot_nr"), "lot_nr"),
        comment=_optional_str(data.get("comment"), "comment"),
        extra=_parse_extra(data.get("extra")),
    )


def _parse_backup_response(payload: Any) -> BackupResponse:
    data = _require_mapping(payload, "backup response")
    return BackupResponse(path=_as_str(_require(data, "path", "backup response"), "path"))


def _parse_extra(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SpoolmanValidationError(f"Expected extra fields to be an object, got {type(value).__name__}.")
    if not all(isinstance(item, str) for item in value.values()):
        raise SpoolmanValidationError("Expected extra field values to be strings.")
    return {str(key): item for key, item in value.items()}
