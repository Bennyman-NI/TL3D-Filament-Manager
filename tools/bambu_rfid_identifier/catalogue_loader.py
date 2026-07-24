from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MANUFACTURER = "Bambu Lab"
SOURCE_REPOSITORY = "piitaya/bambu-filaments"
SOURCE_URL = "https://raw.githubusercontent.com/piitaya/bambu-filaments/main/filaments.json"
LOCAL_SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "catalogues" / "bambu"
DEFAULT_CACHE_PATH = DEFAULT_CACHE_DIR / "filaments.json"
DEFAULT_METADATA_PATH = DEFAULT_CACHE_DIR / "metadata.json"


class CatalogueError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogueRecord:
    id: str
    material: str | None
    product: str | None
    color_name: str | None
    color_hex: str | None
    color_hexes: tuple[str, ...]
    weight: float | int | None
    temp_min: float | int | None
    temp_max: float | int | None
    integrations: dict[str, object]
    raw: dict[str, object] = field(default_factory=dict)

    @property
    def catalogue_name(self) -> str | None:
        return build_catalogue_name(self.product, self.color_name)

    @property
    def material_name(self) -> str | None:
        return self.product

    @property
    def tray_info_variant_id(self) -> str:
        return self.id

    @property
    def tray_info_material_id(self) -> str:
        return ""

    @property
    def filament_type(self) -> str | None:
        return self.material

    @property
    def detailed_filament_type(self) -> str | None:
        return self.product

    @property
    def color_rgba(self) -> str | None:
        return self.color_hex


@dataclass(frozen=True)
class CatalogueData:
    records: dict[str, CatalogueRecord]
    source_name: str
    source_repository: str
    source_checksum: str | None
    source_fetched_at: str | None
    validation_warnings: tuple[str, ...] = ()


def fallback(
    variant_id: str,
    material: str,
    product: str,
    color_name: str,
    color_hex: str,
) -> CatalogueRecord:
    return CatalogueRecord(
        id=variant_id,
        material=material,
        product=product,
        color_name=color_name,
        color_hex=color_hex,
        color_hexes=(color_hex,),
        weight=1000,
        temp_min=None,
        temp_max=None,
        integrations={},
        raw={
            "id": variant_id,
            "material": material,
            "product": product,
            "color_name": color_name,
            "color_hex": color_hex,
            "color_hexes": [color_hex],
            "weight": 1000,
            "temp_min": None,
            "temp_max": None,
            "integrations": {},
        },
    )


@dataclass(frozen=True)
class CatalogueMatch:
    manufacturer: str
    catalogue_name: str | None
    material_name: str | None
    color_name: str | None
    status: str
    source: str
    entry_id: str | None
    source_repository: str | None
    source_checksum: str | None
    source_fetched_at: str | None
    validation_warnings: tuple[str, ...] = ()


FALLBACK_RECORDS: tuple[CatalogueRecord, ...] = (
    fallback("A00-B9", "PLA", "PLA Basic", "Blue", "0A2989FF"),
    fallback("A00-R3", "PLA", "PLA Basic", "Hot Pink", "F5547CFF"),
    fallback("A00-G6", "PLA", "PLA Basic", "Green", "00AE42FF"),
    fallback("A00-A1", "PLA", "PLA Basic", "Pumpkin Orange", "FF9016FF"),
    fallback("A00-G3", "PLA", "PLA Basic", "Bright Green", "BECF00FF"),
    fallback("A01-Y3", "PLA", "PLA Matte", "Desert Tan", "E8DBB7FF"),
    fallback("A01-K1", "PLA", "PLA Matte", "Charcoal", "000000FF"),
    fallback("A01-R2", "PLA", "PLA Matte", "Terracotta", "B15533FF"),
    fallback("A06-D1", "PLA", "PLA Silk+", "Silver", "C8C8C8FF"),
    fallback("G00-D00", "PETG", "PETG Basic", "Gray", "7F7E83FF"),
    fallback("G00-B00", "PETG", "PETG Basic", "Blue", "001489FF"),
    fallback("G00-Y00", "PETG", "PETG Basic", "Yellow", "FCE300FF"),
    fallback("G02-K0", "PETG", "PETG HF", "Black", "000000FF"),
)


def resolve_catalogue(fields: dict[str, object]) -> CatalogueMatch:
    return resolve_catalogue_with_cache(fields, DEFAULT_CACHE_DIR)


def resolve_catalogue_with_cache(fields: dict[str, object], cache_dir: Path) -> CatalogueMatch:
    cache = load_cache_or_none(cache_dir / "filaments.json", cache_dir / "metadata.json")
    fallback_catalogue = fallback_catalogue_data()
    variant_id = as_string(fields.get("tray_info_variant_id"))
    if not variant_id:
        return unknown("unknown", None, ("Cannot resolve Bambu catalogue entry; missing tray_info_variant_id.",))

    if cache is not None:
        cache_record = cache.records.get(variant_id)
        fallback_record = fallback_catalogue.records.get(variant_id)
        if cache_record is not None:
            warnings = validation_warnings(cache_record, fields)
            if fallback_record is not None and records_conflict(cache_record, fallback_record):
                warnings.append(f"Downloaded catalogue entry {variant_id} conflicts with bundled validated fallback.")
            return match_from_record(cache_record, cache, fields, warnings)
        if fallback_record is not None:
            warnings = [f"Variant {variant_id} was absent from downloaded cache; using bundled validated fallback."]
            warnings.extend(validation_warnings(fallback_record, fields))
            return match_from_record(fallback_record, fallback_catalogue, fields, warnings)

    fallback_record = fallback_catalogue.records.get(variant_id)
    if fallback_record is not None:
        return match_from_record(fallback_record, fallback_catalogue, fields, validation_warnings(fallback_record, fields))
    return unknown("unknown", None, (f"No Bambu catalogue entry found for variant ID {variant_id}.",))


def load_cache_or_none(
    cache_path: Path = DEFAULT_CACHE_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
) -> CatalogueData | None:
    try:
        return load_cache(cache_path, metadata_path)
    except (CatalogueError, OSError, json.JSONDecodeError):
        return None


def load_cache(cache_path: Path = DEFAULT_CACHE_PATH, metadata_path: Path = DEFAULT_METADATA_PATH) -> CatalogueData:
    raw_bytes = cache_path.read_bytes()
    records = validate_catalogue_bytes(raw_bytes)
    metadata = read_metadata(metadata_path)
    checksum = metadata.get("sha256")
    fetched_at = metadata.get("fetched_at_utc")
    return CatalogueData(
        records={record.id: record for record in records},
        source_name=f"{SOURCE_REPOSITORY} cache",
        source_repository=as_string(metadata.get("source_repository")) or SOURCE_REPOSITORY,
        source_checksum=checksum if isinstance(checksum, str) else sha256_hex(raw_bytes),
        source_fetched_at=fetched_at if isinstance(fetched_at, str) else None,
    )


def fallback_catalogue_data() -> CatalogueData:
    return CatalogueData(
        records={record.id: record for record in FALLBACK_RECORDS},
        source_name="bundled validated fallback",
        source_repository="TL3D bundled validated fallback",
        source_checksum=bundled_fallback_checksum(),
        source_fetched_at=None,
    )


def validate_catalogue_bytes(raw_bytes: bytes) -> list[CatalogueRecord]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CatalogueError(f"Catalogue is not valid UTF-8: {exc}.") from exc
    except json.JSONDecodeError as exc:
        raise CatalogueError(f"Catalogue JSON is invalid: {exc}.") from exc
    return validate_catalogue_payload(payload)


def validate_catalogue_payload(payload: object) -> list[CatalogueRecord]:
    if not isinstance(payload, list):
        raise CatalogueError("Catalogue JSON must contain a list of filament records.")

    seen: set[str] = set()
    records: list[CatalogueRecord] = []
    errors: list[str] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            errors.append(f"record {index}: expected object")
            continue

        try:
            record = validate_record(entry, index)
        except CatalogueError as exc:
            errors.append(str(exc))
            continue

        if record.id in seen:
            errors.append(f"record {index}: duplicate variant id {record.id!r}")
            continue
        seen.add(record.id)
        records.append(record)

    if errors:
        raise CatalogueError("Invalid Bambu catalogue: " + "; ".join(errors))
    return records


def validate_record(entry: dict[str, object], index: int) -> CatalogueRecord:
    record_id = required_string(entry.get("id"), index, "id")
    material = optional_string(entry.get("material"), index, "material")
    product = optional_string(entry.get("product"), index, "product")
    color_name = optional_string(entry.get("color_name"), index, "color_name")
    color_hex = optional_color(entry.get("color_hex"), index, "color_hex")
    color_hexes = optional_color_list(entry.get("color_hexes"), index, "color_hexes")
    weight = optional_number(entry.get("weight"), index, "weight")
    temp_min = optional_number(entry.get("temp_min"), index, "temp_min")
    temp_max = optional_number(entry.get("temp_max"), index, "temp_max")
    integrations = optional_object(entry.get("integrations"), index, "integrations")
    return CatalogueRecord(
        id=record_id,
        material=material,
        product=product,
        color_name=color_name,
        color_hex=color_hex,
        color_hexes=tuple(color_hexes),
        weight=weight,
        temp_min=temp_min,
        temp_max=temp_max,
        integrations=integrations,
        raw=dict(entry),
    )


def match_from_record(
    record: CatalogueRecord,
    catalogue: CatalogueData,
    fields: dict[str, object],
    warnings: list[str],
) -> CatalogueMatch:
    status = "identifier_match_with_warning" if warnings else "exact"
    return CatalogueMatch(
        manufacturer=MANUFACTURER,
        catalogue_name=record.catalogue_name,
        material_name=record.product,
        color_name=record.color_name,
        status=status,
        source=catalogue.source_name,
        entry_id=record.id,
        source_repository=catalogue.source_repository,
        source_checksum=catalogue.source_checksum,
        source_fetched_at=catalogue.source_fetched_at,
        validation_warnings=tuple(warnings),
    )


def validation_warnings(record: CatalogueRecord, fields: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    decoded_material = as_string(fields.get("filament_type"))
    decoded_product = as_string(fields.get("detailed_filament_type"))
    decoded_color = color_hex(fields.get("color_rgba"))
    if decoded_material and record.material and decoded_material != record.material:
        warnings.append(f"Decoded material {decoded_material} differs from catalogue material {record.material}.")
    if decoded_product and record.product and decoded_product != record.product:
        warnings.append(f"Decoded product {decoded_product} differs from catalogue product {record.product}.")
    accepted_colors = set(record.color_hexes)
    if record.color_hex:
        accepted_colors.add(record.color_hex)
    if decoded_color and accepted_colors and decoded_color not in accepted_colors:
        warnings.append(f"Decoded RGBA {decoded_color} differs from catalogue colour {sorted(accepted_colors)[0]}.")
    return warnings


def records_conflict(cache_record: CatalogueRecord, fallback_record: CatalogueRecord) -> bool:
    return (
        cache_record.material != fallback_record.material
        or cache_record.product != fallback_record.product
        or cache_record.color_name != fallback_record.color_name
        or cache_record.color_hex != fallback_record.color_hex
    )


def unknown(source: str, repository: str | None, warnings: tuple[str, ...]) -> CatalogueMatch:
    return CatalogueMatch(
        manufacturer=MANUFACTURER,
        catalogue_name=None,
        material_name=None,
        color_name=None,
        status="unknown",
        source=source,
        entry_id=None,
        source_repository=repository,
        source_checksum=None,
        source_fetched_at=None,
        validation_warnings=warnings,
    )


def build_catalogue_name(product: str | None, color_name: str | None) -> str | None:
    if not product or not color_name:
        return None
    parts = [MANUFACTURER]
    product_without_manufacturer = strip_bambu_prefix(product)
    parts.append(product_without_manufacturer)
    if color_name not in product_without_manufacturer.split():
        parts.append(color_name)
    return " ".join(part for part in parts if part)


def strip_bambu_prefix(value: str) -> str:
    for prefix in ("Bambu Lab ", "Bambu "):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def read_metadata(metadata_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_hex(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def bundled_fallback_checksum() -> str:
    payload = json.dumps([record.raw for record in FALLBACK_RECORDS], sort_keys=True).encode("utf-8")
    return sha256_hex(payload)


def required_string(value: object, index: int, field_name: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise CatalogueError(f"record {index}: {field_name} must be a non-empty string")


def optional_string(value: object, index: int, field_name: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise CatalogueError(f"record {index}: {field_name} must be a string or null")


def optional_color(value: object, index: int, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and is_color_hex(value):
        return value
    raise CatalogueError(f"record {index}: {field_name} must be uppercase 8-character RRGGBBAA hex or null")


def optional_color_list(value: object, index: int, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CatalogueError(f"record {index}: {field_name} must be a list")
    colors: list[str] = []
    for color_index, color in enumerate(value):
        if not isinstance(color, str) or not is_color_hex(color):
            raise CatalogueError(
                f"record {index}: {field_name}[{color_index}] must be uppercase 8-character RRGGBBAA hex"
            )
        colors.append(color)
    return colors


def optional_number(value: object, index: int, field_name: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CatalogueError(f"record {index}: {field_name} must be a number or null")
    return value


def optional_object(value: object, index: int, field_name: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CatalogueError(f"record {index}: {field_name} must be an object when present")
    return dict(value)


def is_color_hex(value: str) -> bool:
    return len(value) == 8 and value.upper() == value and all(character in "0123456789ABCDEF" for character in value)


def as_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def color_hex(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    hex_value = value.get("hex")
    return hex_value if isinstance(hex_value, str) and hex_value else None
