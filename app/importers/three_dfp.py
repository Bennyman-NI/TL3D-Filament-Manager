from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Iterable

from app.spoolman_client import (
    CreateFilamentRequest,
    CreateSpoolRequest,
    CreateVendorRequest,
    Filament,
    Spool,
    SpoolmanClient,
    Vendor,
)

SPOOL_UUID_COMMENT_MARKER = "3DFP spool UUID:"


@dataclass(frozen=True)
class ThreeDfpRow:
    row_number: int
    spool_uuid: str
    manufacturer: str
    material: str
    material_subtype: str | None = None
    color_name: str | None = None
    color_hex: str | None = None
    multi_color_hexes: str | None = None
    multi_color_direction: str | None = None
    remaining_weight: float | None = None
    initial_weight: float | None = None
    location: str | None = None
    purchase_price: float | None = None
    notes: str | None = None
    purchase_notes: str | None = None
    purchase_date: str | None = None
    purchase_currency: str | None = None
    spool_url: str | None = None
    filament_url: str | None = None
    updated_at: str | None = None
    td_value: str | None = None
    spool_td_value: str | None = None
    spool_k_value: str | None = None
    spool_flow_ratio: str | None = None
    nozzle_temperature: int | None = None
    bed_temperature: int | None = None
    empty_spool_weight: float | None = None
    diameter: float = 1.75
    density: float = 1.24
    article_number: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class ImportErrorDetail:
    row_number: int
    message: str


@dataclass(frozen=True)
class ImportAction:
    row_number: int
    action: str
    message: str


@dataclass(frozen=True)
class ThreeDfpImportReport:
    dry_run: bool
    rows_seen: int = 0
    rows_valid: int = 0
    vendors_created: int = 0
    vendors_reused: int = 0
    filaments_created: int = 0
    filaments_reused: int = 0
    spools_created: int = 0
    spools_skipped: int = 0
    backup_path: str | None = None
    actions: list[ImportAction] = field(default_factory=list)
    errors: list[ImportErrorDetail] = field(default_factory=list)


@dataclass(frozen=True)
class FilamentKey:
    vendor_name: str
    material: str
    material_subtype: str | None
    color_name: str | None
    color_hex: str | None
    multi_color_hexes: str | None
    diameter: float
    density: float
    article_number: str | None
    external_id: str | None


class ThreeDfpImporter:
    def __init__(self, client: SpoolmanClient) -> None:
        self.client = client

    def dry_run(self, csv_source: str | Path | IO[str]) -> ThreeDfpImportReport:
        return self.import_csv(csv_source, apply=False)

    def apply(self, csv_source: str | Path | IO[str]) -> ThreeDfpImportReport:
        return self.import_csv(csv_source, apply=True)

    def import_csv(self, csv_source: str | Path | IO[str], *, apply: bool) -> ThreeDfpImportReport:
        rows, errors, rows_seen = parse_csv(csv_source)
        actions: list[ImportAction] = []

        existing_vendors = _index_vendors(self.client.list_vendors())
        existing_filaments = _index_filaments(self.client.list_filaments())
        imported_spool_uuids = _imported_spool_uuids(self.client.list_spools(allow_archived=True))

        vendor_cache: dict[str, Vendor | None] = {}
        filament_cache: dict[FilamentKey, Filament | None] = {}
        vendors_created = 0
        vendors_reused = 0
        filaments_created = 0
        filaments_reused = 0
        spools_created = 0
        spools_skipped = 0
        backup_path: str | None = None

        valid_rows = 0
        if apply and rows:
            backup_path = self.client.create_backup().path

        for row in rows:
            valid_rows += 1
            try:
                if row.spool_uuid in imported_spool_uuids:
                    spools_skipped += 1
                    actions.append(
                        ImportAction(row.row_number, "skip_spool", f"Spool {row.spool_uuid} was already imported.")
                    )
                    continue

                vendor_key = _normalize_key(row.manufacturer)
                vendor = vendor_cache.get(vendor_key)
                if vendor_key not in vendor_cache:
                    vendor = existing_vendors.get(vendor_key)
                    if vendor is None:
                        actions.append(ImportAction(row.row_number, "create_vendor", row.manufacturer))
                        if apply:
                            vendor = self.client.create_vendor(
                                CreateVendorRequest(
                                    name=row.manufacturer,
                                    comment=_compact_comment(["Created from 3D Filament Profiles import."]),
                                )
                            )
                            existing_vendors[vendor_key] = vendor
                        vendors_created += 1
                    else:
                        vendors_reused += 1
                        actions.append(ImportAction(row.row_number, "reuse_vendor", row.manufacturer))
                    vendor_cache[vendor_key] = vendor

                filament_key = _filament_key(row)
                filament = filament_cache.get(filament_key)
                if filament_key not in filament_cache:
                    filament = _find_existing_filament(existing_filaments, filament_key)
                    if filament is None:
                        actions.append(ImportAction(row.row_number, "create_filament", _filament_name(row)))
                        if apply:
                            filament = self.client.create_filament(_create_filament_request(row, vendor))
                            existing_filaments.append(filament)
                        filaments_created += 1
                    else:
                        filaments_reused += 1
                        actions.append(ImportAction(row.row_number, "reuse_filament", _filament_name(row)))
                    filament_cache[filament_key] = filament

                actions.append(ImportAction(row.row_number, "create_spool", row.spool_uuid))
                if apply:
                    if filament is None:
                        raise ValueError("Cannot create spool before its filament exists.")
                    self.client.create_spool(_create_spool_request(row, filament.id))
                    imported_spool_uuids.add(row.spool_uuid)
                spools_created += 1
            except Exception as exc:  # noqa: BLE001 - row-level import should continue.
                errors.append(ImportErrorDetail(row.row_number, str(exc)))

        return ThreeDfpImportReport(
            dry_run=not apply,
            rows_seen=rows_seen,
            rows_valid=valid_rows,
            vendors_created=vendors_created,
            vendors_reused=vendors_reused,
            filaments_created=filaments_created,
            filaments_reused=filaments_reused,
            spools_created=spools_created,
            spools_skipped=spools_skipped,
            backup_path=backup_path,
            actions=actions,
            errors=errors,
        )


def parse_csv(csv_source: str | Path | IO[str]) -> tuple[list[ThreeDfpRow], list[ImportErrorDetail], int]:
    with _open_csv(csv_source) as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return [], [ImportErrorDetail(1, "CSV file is missing a header row.")], 0

        rows: list[ThreeDfpRow] = []
        errors: list[ImportErrorDetail] = []
        row_count = 0
        for raw_number, raw_row in enumerate(reader, start=2):
            row_count += 1
            try:
                rows.append(_parse_row(raw_number, raw_row))
            except ValueError as exc:
                errors.append(ImportErrorDetail(raw_number, str(exc)))
        return rows, errors, row_count


def spool_uuid_marker(spool_uuid: str) -> str:
    return f"{SPOOL_UUID_COMMENT_MARKER} {spool_uuid}"


def _parse_row(row_number: int, row: dict[str, str | None]) -> ThreeDfpRow:
    spool_uuid = _required(row, "spool uuid", _COLUMN_ALIASES["spool_uuid"])
    manufacturer = _required(row, "manufacturer", _COLUMN_ALIASES["manufacturer"])
    material = _required(row, "material", _COLUMN_ALIASES["material"])
    color_hex, multi_color_hexes, multi_color_direction = _parse_rgb(_optional(row, _COLUMN_ALIASES["rgb"]))

    return ThreeDfpRow(
        row_number=row_number,
        spool_uuid=spool_uuid,
        manufacturer=manufacturer,
        material=material,
        material_subtype=_optional(row, _COLUMN_ALIASES["material_subtype"]),
        color_name=_optional(row, _COLUMN_ALIASES["color_name"]),
        color_hex=color_hex,
        multi_color_hexes=multi_color_hexes,
        multi_color_direction=multi_color_direction,
        remaining_weight=_optional_float(row, _COLUMN_ALIASES["remaining_weight"], "remaining weight"),
        initial_weight=_optional_float(row, _COLUMN_ALIASES["initial_weight"], "initial weight"),
        location=_optional(row, _COLUMN_ALIASES["location"]),
        purchase_price=_optional_float(row, _COLUMN_ALIASES["purchase_price"], "purchase price"),
        notes=_optional(row, _COLUMN_ALIASES["notes"]),
        purchase_notes=_optional(row, _COLUMN_ALIASES["purchase_notes"]),
        purchase_date=_optional(row, _COLUMN_ALIASES["purchase_date"]),
        purchase_currency=_optional(row, _COLUMN_ALIASES["purchase_currency"]),
        spool_url=_optional(row, _COLUMN_ALIASES["spool_url"]),
        filament_url=_optional(row, _COLUMN_ALIASES["filament_url"]),
        updated_at=_optional(row, _COLUMN_ALIASES["updated_at"]),
        td_value=_optional(row, _COLUMN_ALIASES["td_value"]),
        spool_td_value=_optional(row, _COLUMN_ALIASES["spool_td_value"]),
        spool_k_value=_optional(row, _COLUMN_ALIASES["spool_k_value"]),
        spool_flow_ratio=_optional(row, _COLUMN_ALIASES["spool_flow_ratio"]),
        nozzle_temperature=_optional_int(row, _COLUMN_ALIASES["nozzle_temperature"], "nozzle temperature"),
        bed_temperature=_optional_int(row, _COLUMN_ALIASES["bed_temperature"], "bed temperature"),
        empty_spool_weight=_optional_float(row, _COLUMN_ALIASES["empty_spool_weight"], "empty spool weight"),
        diameter=_optional_float(row, _COLUMN_ALIASES["diameter"], "diameter") or 1.75,
        density=_optional_float(row, _COLUMN_ALIASES["density"], "density") or 1.24,
        article_number=_optional(row, _COLUMN_ALIASES["article_number"]),
        external_id=_optional(row, _COLUMN_ALIASES["external_id"]),
    )


def _create_filament_request(row: ThreeDfpRow, vendor: Vendor | None) -> CreateFilamentRequest:
    return CreateFilamentRequest(
        name=_filament_name(row),
        vendor_id=vendor.id if vendor is not None else None,
        material=row.material,
        density=row.density,
        diameter=row.diameter,
        price=row.purchase_price,
        weight=row.initial_weight,
        spool_weight=row.empty_spool_weight,
        article_number=row.article_number,
        comment=_filament_comment(row),
        settings_extruder_temp=row.nozzle_temperature,
        settings_bed_temp=row.bed_temperature,
        color_hex=row.color_hex if row.multi_color_hexes is None else None,
        multi_color_hexes=row.multi_color_hexes,
        multi_color_direction=row.multi_color_direction,
        external_id=row.external_id,
    )


def _create_spool_request(row: ThreeDfpRow, filament_id: int) -> CreateSpoolRequest:
    return CreateSpoolRequest(
        filament_id=filament_id,
        price=row.purchase_price,
        initial_weight=row.initial_weight,
        spool_weight=row.empty_spool_weight,
        remaining_weight=row.remaining_weight,
        location=row.location,
        lot_nr=None,
        comment=_spool_comment(row),
        archived=False,
    )


def _filament_name(row: ThreeDfpRow) -> str:
    parts = [row.material_subtype, row.color_name]
    name = " ".join(part for part in parts if part)
    return name or row.material


def _filament_comment(row: ThreeDfpRow) -> str:
    return _compact_comment(
        [
            "Imported from 3D Filament Profiles.",
            f"Manufacturer: {row.manufacturer}",
            f"Material subtype: {row.material_subtype}" if row.material_subtype else None,
            f"Colour name: {row.color_name}" if row.color_name else None,
            f"Colour hex: {row.color_hex}" if row.color_hex else None,
            f"Multicolour values: {row.multi_color_hexes}" if row.multi_color_hexes else None,
            f"Preferred nozzle temperature: {row.nozzle_temperature} C" if row.nozzle_temperature is not None else None,
            f"Preferred bed temperature: {row.bed_temperature} C" if row.bed_temperature is not None else None,
        ]
    )


def _spool_comment(row: ThreeDfpRow) -> str:
    return _compact_comment(
        [
            spool_uuid_marker(row.spool_uuid),
            "Imported from 3D Filament Profiles.",
            f"Manufacturer: {row.manufacturer}",
            f"Material: {row.material}",
            f"Material subtype: {row.material_subtype}" if row.material_subtype else None,
            f"Colour name: {row.color_name}" if row.color_name else None,
            f"Colour hex: {row.color_hex}" if row.color_hex else None,
            f"Multicolour values: {row.multi_color_hexes}" if row.multi_color_hexes else None,
            f"Purchase date: {row.purchase_date}" if row.purchase_date else None,
            f"Notes: {row.notes}" if row.notes else None,
            f"Purchase notes: {row.purchase_notes}" if row.purchase_notes else None,
            f"Purchase currency: {row.purchase_currency}" if row.purchase_currency else None,
            f"Spool URL: {row.spool_url}" if row.spool_url else None,
            f"Filament URL: {row.filament_url}" if row.filament_url else None,
            f"Updated at: {row.updated_at}" if row.updated_at else None,
            f"TD value: {row.td_value}" if row.td_value else None,
            f"Spool TD value: {row.spool_td_value}" if row.spool_td_value else None,
            f"Spool K value: {row.spool_k_value}" if row.spool_k_value else None,
            f"Spool flow ratio: {row.spool_flow_ratio}" if row.spool_flow_ratio else None,
        ]
    )


def _filament_key(row: ThreeDfpRow) -> FilamentKey:
    return FilamentKey(
        vendor_name=_normalize_key(row.manufacturer),
        material=_normalize_key(row.material),
        material_subtype=_normalize_optional_key(row.material_subtype),
        color_name=_normalize_optional_key(row.color_name),
        color_hex=_normalize_optional_key(row.color_hex),
        multi_color_hexes=_normalize_optional_key(row.multi_color_hexes),
        diameter=row.diameter,
        density=row.density,
        article_number=_normalize_optional_key(row.article_number),
        external_id=_normalize_optional_key(row.external_id),
    )


def _index_vendors(vendors: Iterable[Vendor]) -> dict[str, Vendor]:
    return {_normalize_key(vendor.name): vendor for vendor in vendors}


def _index_filaments(filaments: Iterable[Filament]) -> list[Filament]:
    return list(filaments)


def _find_existing_filament(filaments: list[Filament], key: FilamentKey) -> Filament | None:
    for filament in filaments:
        if key.external_id and _normalize_optional_key(filament.external_id) == key.external_id:
            return filament
        vendor_name = _normalize_optional_key(filament.vendor.name if filament.vendor else None)
        if (
            vendor_name == key.vendor_name
            and _normalize_optional_key(filament.material) == key.material
            and _normalize_optional_key(filament.name) == _normalize_optional_key(" ".join(
                part for part in [key.material_subtype, key.color_name] if part
            ) or key.material)
            and _normalize_optional_key(filament.color_hex) == key.color_hex
            and _normalize_optional_key(filament.multi_color_hexes) == key.multi_color_hexes
            and filament.diameter == key.diameter
            and filament.density == key.density
        ):
            return filament
    return None


def _imported_spool_uuids(spools: Iterable[Spool]) -> set[str]:
    imported: set[str] = set()
    pattern = re.compile(rf"{re.escape(SPOOL_UUID_COMMENT_MARKER)}\s*([^\s;|]+)")
    for spool in spools:
        if not spool.comment:
            continue
        match = pattern.search(spool.comment)
        if match:
            imported.add(match.group(1))
    return imported


def _compact_comment(lines: list[str | None]) -> str:
    return "\n".join(line for line in lines if line)


def _normalize_key(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _normalize_optional_key(value: str | None) -> str | None:
    return _normalize_key(value) if value else None


def _required(row: dict[str, str | None], field_name: str, aliases: tuple[str, ...]) -> str:
    value = _optional(row, aliases)
    if value is None:
        raise ValueError(f"Missing required {field_name}.")
    return value


def _optional(row: dict[str, str | None], aliases: tuple[str, ...]) -> str | None:
    normalized = {_normalize_header(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_normalize_header(alias))
        if value is not None and value.strip():
            return value.strip()
    return None


def _optional_float(row: dict[str, str | None], aliases: tuple[str, ...], field_name: str) -> float | None:
    value = _optional(row, aliases)
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value!r}.") from exc


def _optional_int(row: dict[str, str | None], aliases: tuple[str, ...], field_name: str) -> int | None:
    value = _optional(row, aliases)
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value!r}.") from exc


def _normalize_hex(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().removeprefix("#").upper()


def _normalize_multi_hex(value: str | None) -> str | None:
    if value is None:
        return None
    return ",".join(_normalize_hex(part) or "" for part in re.split(r"[,;|]", value) if part.strip())


def _parse_rgb(value: str | None) -> tuple[str | None, str | None, str | None]:
    if value is None:
        return None, None, None
    colors = [_normalize_hex(part) for part in value.split(",") if part.strip()]
    colors = [color for color in colors if color]
    if len(colors) <= 1:
        return colors[0] if colors else None, None, None
    return None, ",".join(colors), "coaxial"


def _normalize_header(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


class _NullContext:
    def __init__(self, value: IO[str]) -> None:
        self.value = value

    def __enter__(self) -> IO[str]:
        return self.value

    def __exit__(self, *_args: object) -> None:
        return None


def _open_csv(csv_source: str | Path | IO[str]) -> Any:
    if hasattr(csv_source, "read"):
        return _NullContext(csv_source)  # type: ignore[arg-type]
    return Path(csv_source).open("r", encoding="utf-8-sig", newline="")


_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "spool_uuid": ("id", "spool_uuid", "spool uuid", "uuid"),
    "manufacturer": ("manufacturer", "brand", "vendor", "maker"),
    "material": ("material", "filament type", "type"),
    "material_subtype": ("material_type", "material subtype", "subtype", "variant", "material variant"),
    "color_name": ("colour name", "color name", "colour", "color"),
    "rgb": ("rgb", "colour hex", "color hex", "hex", "hex color", "hex colour"),
    "remaining_weight": ("remaining_grams", "remaining weight", "remaining weight g", "remaining_weight", "remaining"),
    "initial_weight": ("initial weight", "initial weight g", "spool weight", "net weight", "weight"),
    "location": ("location", "storage location"),
    "purchase_price": ("spool_purchase_price", "purchase price", "price", "cost"),
    "notes": ("notes", "note", "comment", "comments"),
    "purchase_notes": ("spool_purchase_notes", "purchase notes"),
    "purchase_date": ("spool_purchase_date", "purchase date", "date purchased", "purchased"),
    "purchase_currency": ("spool_purchase_currency", "purchase currency", "currency"),
    "spool_url": ("spool_url", "spool url"),
    "filament_url": ("filament_url", "filament url"),
    "updated_at": ("updated_at", "updated at"),
    "td_value": ("td_value", "td value"),
    "spool_td_value": ("spool_td_value", "spool td value"),
    "spool_k_value": ("spool_k_value", "spool k value"),
    "spool_flow_ratio": ("spool_flow_ratio", "spool flow ratio"),
    "nozzle_temperature": (
        "spool_preferred_nozzle_temp",
        "nozzle temperature",
        "extruder temperature",
        "print temperature",
        "hotend temperature",
    ),
    "bed_temperature": ("spool_preferred_bed_temp", "bed temperature", "bed temp"),
    "empty_spool_weight": ("spool_empty_spool_weight", "empty spool weight", "tare weight", "spool tare"),
    "diameter": ("diameter", "filament diameter"),
    "density": ("density", "filament density"),
    "article_number": ("article number", "sku", "product code", "ean"),
    "external_id": ("external id", "external_id"),
}
