from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from . import memory_inspector
except ImportError:  # pragma: no cover - supports direct script-style imports in tests
    import memory_inspector


SUPPORTED_SCHEMA_VERSION = 1
BLOCK_SIZE_BYTES = 16
TRAILER_BLOCK_INDEX = 3
SIGNATURE_SECTORS = set(range(10, 16))


@dataclass(frozen=True)
class DecodedMetadata:
    schema_version: int | None
    created_at: str | None
    reader_name: str | None
    uid: str | None
    atr: str | None
    tag_type: str | None
    dump_status: str | None


@dataclass(frozen=True)
class DecodedField:
    name: str
    value: object
    source: str
    description: str


@dataclass(frozen=True)
class RawField:
    name: str
    source: str
    data_hex: str | None
    reason: str


@dataclass(frozen=True)
class DecodedDump:
    metadata: DecodedMetadata
    fields: list[DecodedField] = field(default_factory=list)
    raw_unknown: list[RawField] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BlockBytes:
    sector: int
    block: int
    absolute_block: int
    data: bytes | None
    status: str
    error: str | None = None

    @property
    def source(self) -> str:
        return f"sector {self.sector} block {self.block} absolute {self.absolute_block}"

    @property
    def data_hex(self) -> str | None:
        return self.data.hex().upper() if self.data is not None else None


def decode_file(path: Path | str) -> DecodedDump:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return decode_dump_dict({}, initial_errors=[f"Malformed JSON: {exc}"])
    except OSError as exc:
        return decode_dump_dict({}, initial_errors=[f"Could not read dump file: {exc}"])

    if not isinstance(payload, dict):
        return decode_dump_dict({}, initial_errors=["Dump JSON must contain an object at the top level."])
    return decode_dump_dict(payload)


def decode_raw_dump(dump: memory_inspector.RawDump) -> DecodedDump:
    return decode_dump_dict(dump.to_dict())


def decode_dump_dict(payload: dict[str, Any], initial_errors: list[str] | None = None) -> DecodedDump:
    errors = [] if initial_errors is None else list(initial_errors)
    warnings: list[str] = []
    metadata = extract_metadata(payload)

    if metadata.schema_version != SUPPORTED_SCHEMA_VERSION:
        errors.append(f"Unsupported dump schema version: {metadata.schema_version!r}.")

    if metadata.dump_status not in {None, "success"}:
        warnings.append(f"Raw dump status is {metadata.dump_status!r}; decoded values may be incomplete.")

    block_lookup = build_block_lookup(payload, warnings, errors)
    result = DecodedDump(metadata=metadata, warnings=warnings, errors=errors)

    decode_documented_fields(block_lookup, result)
    preserve_known_raw_regions(block_lookup, result)
    return result


def extract_metadata(payload: dict[str, Any]) -> DecodedMetadata:
    return DecodedMetadata(
        schema_version=payload.get("schema_version"),
        created_at=payload.get("created_at"),
        reader_name=payload.get("reader_name"),
        uid=payload.get("uid"),
        atr=payload.get("atr"),
        tag_type=payload.get("tag_type"),
        dump_status=payload.get("status"),
    )


def build_block_lookup(
    payload: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> dict[tuple[int, int], BlockBytes]:
    sectors = payload.get("sectors")
    if not isinstance(sectors, list):
        errors.append("Dump is missing a sectors list.")
        return {}

    lookup: dict[tuple[int, int], BlockBytes] = {}
    seen_sectors: set[int] = set()
    for sector_entry in sectors:
        if not isinstance(sector_entry, dict):
            warnings.append("Ignoring malformed sector entry.")
            continue

        sector = sector_entry.get("sector")
        if not isinstance(sector, int):
            warnings.append(f"Ignoring sector with invalid sector number: {sector!r}.")
            continue

        seen_sectors.add(sector)
        blocks = sector_entry.get("blocks")
        if not isinstance(blocks, list):
            warnings.append(f"Sector {sector} is missing a blocks list.")
            continue

        seen_blocks: set[int] = set()
        for block_entry in blocks:
            block = parse_block_entry(sector, block_entry, warnings)
            if block is None:
                continue
            seen_blocks.add(block.block)
            lookup[(sector, block.block)] = block

        missing_blocks = sorted(set(range(4)) - seen_blocks)
        if missing_blocks:
            warnings.append(f"Sector {sector} is incomplete; missing blocks {missing_blocks}.")

    missing_sectors = sorted(set(range(16)) - seen_sectors)
    if missing_sectors:
        warnings.append(f"Dump is incomplete; missing sectors {missing_sectors}.")

    return lookup


def parse_block_entry(sector: int, block_entry: object, warnings: list[str]) -> BlockBytes | None:
    if not isinstance(block_entry, dict):
        warnings.append(f"Ignoring malformed block entry in sector {sector}.")
        return None

    block = block_entry.get("block")
    absolute_block = block_entry.get("absolute_block")
    status = block_entry.get("status")
    if not isinstance(block, int) or not isinstance(absolute_block, int):
        warnings.append(f"Ignoring block with invalid numbering in sector {sector}.")
        return None
    if not isinstance(status, str):
        status = "unknown"

    data_hex = block_entry.get("data_hex")
    error = block_entry.get("error")
    data: bytes | None = None
    if status in {"success", "read_warning"}:
        if not isinstance(data_hex, str):
            warnings.append(f"Sector {sector} block {block} has status {status!r} but no hex data.")
        else:
            try:
                data = bytes.fromhex(data_hex)
                if len(data) != BLOCK_SIZE_BYTES:
                    warnings.append(
                        f"Sector {sector} block {block} has {len(data)} bytes; expected {BLOCK_SIZE_BYTES}."
                    )
            except ValueError:
                warnings.append(f"Sector {sector} block {block} contains invalid hexadecimal data.")
    elif error:
        warnings.append(f"Sector {sector} block {block} was not readable: {error}")

    return BlockBytes(
        sector=sector,
        block=block,
        absolute_block=absolute_block,
        data=data,
        status=status,
        error=error if isinstance(error, str) else None,
    )


def decode_documented_fields(blocks: dict[tuple[int, int], BlockBytes], result: DecodedDump) -> None:
    add_string(result, blocks, 0, 1, 0, 8, "tray_info_variant_id", "Tray Info Index - Material Variant ID")
    add_string(result, blocks, 0, 1, 8, 8, "tray_info_material_id", "Tray Info Index - Material ID")
    add_string(result, blocks, 0, 2, 0, 16, "filament_type", "Filament Type")
    add_string(result, blocks, 1, 0, 0, 16, "detailed_filament_type", "Detailed Filament Type")
    add_rgba(result, blocks, 1, 1, 0, "color_rgba", "Color in hex RGBA")
    add_uint16(result, blocks, 1, 1, 4, "spool_weight_grams", "Spool Weight in grams")
    add_float32(result, blocks, 1, 1, 8, "filament_diameter_mm", "Filament Diameter in millimeters")
    add_uint16(result, blocks, 1, 2, 0, "drying_temperature_c", "Drying Temperature in C")
    add_uint16(result, blocks, 1, 2, 2, "drying_time_hours", "Drying time in hours")
    add_uint16(result, blocks, 1, 2, 4, "bed_temperature_type", "Bed Temperature Type")
    add_uint16(result, blocks, 1, 2, 6, "bed_temperature_c", "Bed Temperature in C")
    add_uint16(result, blocks, 1, 2, 8, "hotend_max_temperature_c", "Max Temperature for Hotend in C")
    add_uint16(result, blocks, 1, 2, 10, "hotend_min_temperature_c", "Min Temperature for Hotend in C")
    add_raw_range(result, blocks, 2, 0, 0, 12, "x_cam_info", "X Cam info")
    add_float32(result, blocks, 2, 0, 12, "minimum_nozzle_diameter_mm", "Minimum Nozzle Diameter")
    add_string(result, blocks, 2, 1, 0, 16, "tray_uid", "Tray UID")
    add_scaled_uint16(result, blocks, 2, 2, 4, 100.0, "spool_width_mm", "Spool Width in mm")
    add_string(result, blocks, 3, 0, 0, 16, "production_datetime", "Production Date and Time in ASCII")
    add_string(result, blocks, 3, 1, 0, 16, "short_production_datetime", "Short Production Date/Time")
    add_uint16(result, blocks, 4, 0, 0, "extra_color_format_identifier", "Extra Color Info Format Identifier")
    add_uint16(result, blocks, 4, 0, 2, "extra_color_count", "Extra Color Count")
    add_abgr_as_rgba(result, blocks, 4, 0, 4, "second_color_rgba", "Second color stored as ABGR")


def preserve_known_raw_regions(blocks: dict[tuple[int, int], BlockBytes], result: DecodedDump) -> None:
    for block in blocks.values():
        if block.data is None:
            continue

        if block.sector == 0 and block.block == 0:
            add_unknown(result, "manufacturer_block", block, "UID and tag manufacturer bytes preserved as raw data.")
        elif block.block == TRAILER_BLOCK_INDEX:
            add_unknown(result, "mifare_sector_trailer", block, "MIFARE keys/access bits, not Bambu filament data.")
        elif block.sector in SIGNATURE_SECTORS:
            add_unknown(result, "rsa_signature_block", block, "RSA-2048 signature bytes; not decoded or modified.")
        elif block.sector == 3 and block.block == 2:
            add_unknown(result, "filament_length_uncertain", block, "Documented with uncertainty; preserved until validated.")
        elif block.sector == 4 and block.block == 1:
            add_unknown(result, "unknown_block_17", block, "Marked unknown in upstream documentation.")
        elif (block.sector, block.block) in documented_empty_blocks():
            add_unknown(result, "documented_empty_block", block, "Documented as empty.")


def documented_empty_blocks() -> set[tuple[int, int]]:
    return {
        (4, 2),
        *{(sector, block) for sector in range(5, 10) for block in range(3)},
    }


def get_block(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
) -> BlockBytes | None:
    block_data = blocks.get((sector, block))
    if block_data is None:
        result.warnings.append(f"Cannot decode sector {sector} block {block}; block is missing.")
        return None
    if block_data.data is None:
        result.warnings.append(f"Cannot decode sector {sector} block {block}; block status is {block_data.status}.")
        return None
    return block_data


def add_field(result: DecodedDump, name: str, value: object, block: BlockBytes, description: str) -> None:
    result.fields.append(DecodedField(name=name, value=value, source=block.source, description=description))


def add_unknown(result: DecodedDump, name: str, block: BlockBytes, reason: str) -> None:
    result.raw_unknown.append(RawField(name=name, source=block.source, data_hex=block.data_hex, reason=reason))


def add_string(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
    offset: int,
    length: int,
    name: str,
    description: str,
) -> None:
    block_data = get_block(result, blocks, sector, block)
    if block_data is None:
        return
    raw = block_data.data[offset : offset + length]
    try:
        value = raw.decode("ascii", errors="strict").rstrip("\x00 ").strip()
    except UnicodeDecodeError as exc:
        result.warnings.append(f"Could not decode {name} as ASCII from {block_data.source}: {exc}.")
        add_unknown(result, name, block_data, "String field could not be decoded.")
        return
    add_field(result, name, value, block_data, description)


def add_uint16(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
    offset: int,
    name: str,
    description: str,
) -> None:
    block_data = get_block(result, blocks, sector, block)
    if block_data is None:
        return
    add_field(result, name, int.from_bytes(block_data.data[offset : offset + 2], "little"), block_data, description)


def add_scaled_uint16(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
    offset: int,
    divisor: float,
    name: str,
    description: str,
) -> None:
    block_data = get_block(result, blocks, sector, block)
    if block_data is None:
        return
    raw_value = int.from_bytes(block_data.data[offset : offset + 2], "little")
    add_field(result, name, raw_value / divisor, block_data, description)


def add_float32(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
    offset: int,
    name: str,
    description: str,
) -> None:
    block_data = get_block(result, blocks, sector, block)
    if block_data is None:
        return
    raw = read_field_bytes(result, block_data, offset, 4, name)
    if raw is None:
        return
    add_field(result, name, struct.unpack("<f", raw)[0], block_data, description)


def read_field_bytes(
    result: DecodedDump,
    block_data: BlockBytes,
    offset: int,
    length: int,
    name: str,
) -> bytes | None:
    assert block_data.data is not None
    if len(block_data.data) < offset + length:
        result.warnings.append(
            f"Cannot decode {name} from {block_data.source}; "
            f"needs {length} bytes at offset {offset}, block has {len(block_data.data)} bytes."
        )
        return None
    return block_data.data[offset : offset + length]


def add_rgba(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
    offset: int,
    name: str,
    description: str,
) -> None:
    block_data = get_block(result, blocks, sector, block)
    if block_data is None:
        return
    red, green, blue, alpha = block_data.data[offset : offset + 4]
    add_field(result, name, {"red": red, "green": green, "blue": blue, "alpha": alpha, "hex": f"{red:02X}{green:02X}{blue:02X}{alpha:02X}"}, block_data, description)


def add_abgr_as_rgba(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
    offset: int,
    name: str,
    description: str,
) -> None:
    block_data = get_block(result, blocks, sector, block)
    if block_data is None:
        return
    alpha, blue, green, red = block_data.data[offset : offset + 4]
    add_field(result, name, {"red": red, "green": green, "blue": blue, "alpha": alpha, "hex": f"{red:02X}{green:02X}{blue:02X}{alpha:02X}"}, block_data, description)


def add_raw_range(
    result: DecodedDump,
    blocks: dict[tuple[int, int], BlockBytes],
    sector: int,
    block: int,
    offset: int,
    length: int,
    name: str,
    description: str,
) -> None:
    block_data = get_block(result, blocks, sector, block)
    if block_data is None:
        return
    add_field(result, name, block_data.data[offset : offset + length].hex().upper(), block_data, description)


def format_human_readable(decoded: DecodedDump) -> str:
    lines = [
        "Bambu RFID Decoded Dump",
        f"UID: {decoded.metadata.uid or 'unknown'}",
        f"Reader: {decoded.metadata.reader_name or 'unknown'}",
        f"Dump status: {decoded.metadata.dump_status or 'unknown'}",
    ]
    if decoded.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in decoded.errors)
    if decoded.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in decoded.warnings)
    if decoded.fields:
        lines.append("")
        lines.append("Decoded fields:")
        for item in decoded.fields:
            lines.append(f"- {item.name}: {item.value} ({item.source})")
    if decoded.raw_unknown:
        lines.append("")
        lines.append("Preserved raw/unknown data:")
        for item in decoded.raw_unknown:
            lines.append(f"- {item.name}: {item.data_hex or '-'} ({item.source})")
    return "\n".join(lines)
