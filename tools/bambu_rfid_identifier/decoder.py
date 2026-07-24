from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from . import bambu_catalogue, memory_inspector
except ImportError:  # pragma: no cover - supports direct script-style imports in tests
    import bambu_catalogue
    import memory_inspector


SUPPORTED_SCHEMA_VERSION = 1
BLOCK_SIZE_BYTES = 16
TRAILER_BLOCK_INDEX = 3
SIGNATURE_SECTORS = set(range(10, 16))
RSA_SIGNATURE_EXPECTED_LENGTH_BYTES = 256
RSA_SIGNATURE_PAYLOAD_BLOCK_COUNT = RSA_SIGNATURE_EXPECTED_LENGTH_BYTES // BLOCK_SIZE_BYTES


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
class RsaSignatureBlock:
    sector: int
    block: int
    absolute_block: int
    role: str
    status: str
    data_hex: str | None
    error: str | None
    included_in_signature_hex: bool


@dataclass(frozen=True)
class RsaSignature:
    status: str
    expected_length_bytes: int
    available_length_bytes: int
    hex: str
    verified: bool
    verification_status: str
    blocks: list[RsaSignatureBlock] = field(default_factory=list)


@dataclass(frozen=True)
class DecodedDump:
    metadata: DecodedMetadata
    fields: list[DecodedField] = field(default_factory=list)
    raw_unknown: list[RawField] = field(default_factory=list)
    rsa_signature: RsaSignature | None = None
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
    resolve_catalogue_fields(result)
    object.__setattr__(result, "rsa_signature", assemble_rsa_signature(block_lookup, result))
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
    add_raw_range(result, blocks, 2, 1, 0, 16, "tray_uid", "Tray UID as raw hexadecimal bytes")
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


def add_resolved_field(result: DecodedDump, name: str, value: object, source: str, description: str) -> None:
    result.fields.append(DecodedField(name=name, value=value, source=source, description=description))


def add_unknown(result: DecodedDump, name: str, block: BlockBytes, reason: str) -> None:
    result.raw_unknown.append(RawField(name=name, source=block.source, data_hex=block.data_hex, reason=reason))


def resolve_catalogue_fields(result: DecodedDump) -> None:
    match = bambu_catalogue.resolve_catalogue({item.name: item.value for item in result.fields})
    result.warnings.extend(match.validation_warnings)

    source = f"bambu catalogue resolver: {match.source}"
    add_resolved_field(result, "manufacturer", match.manufacturer, source, "Resolved manufacturer.")
    add_resolved_field(result, "catalogue_name", match.catalogue_name, source, "Resolved official Bambu catalogue name.")
    add_resolved_field(result, "material_name", match.material_name, source, "Resolved official material name.")
    add_resolved_field(result, "color_name", match.color_name, source, "Resolved official colour name.")
    add_resolved_field(result, "catalogue_match_status", match.status, source, "Catalogue match status.")
    add_resolved_field(result, "catalogue_match_source", match.source, source, "Catalogue match source.")
    add_resolved_field(result, "catalogue_entry_id", match.entry_id, source, "Catalogue variant ID.")
    add_resolved_field(result, "catalogue_source_repository", match.source_repository, source, "Catalogue source repository.")
    add_resolved_field(result, "catalogue_source_checksum", match.source_checksum, source, "Catalogue source checksum.")
    add_resolved_field(result, "catalogue_source_fetched_at", match.source_fetched_at, source, "Catalogue source fetch timestamp.")
    add_resolved_field(
        result,
        "catalogue_validation_warnings",
        list(match.validation_warnings),
        source,
        "Catalogue validation warnings.",
    )
    if match.conflict is not None:
        add_resolved_field(
            result,
            "catalogue_conflict",
            {
                "identifier": match.conflict.identifier,
                "differing_fields": list(match.conflict.differing_fields),
                "downloaded": match.conflict.downloaded,
                "bundled_fallback": match.conflict.bundled_fallback,
            },
            source,
            "Downloaded catalogue versus bundled fallback conflict diagnostic.",
        )


def assemble_rsa_signature(
    blocks: dict[tuple[int, int], BlockBytes],
    result: DecodedDump,
) -> RsaSignature:
    ordered_positions = [(sector, block) for sector in range(10, 16) for block in range(4)]
    payload_positions = [(sector, block) for sector, block in ordered_positions if block != TRAILER_BLOCK_INDEX]
    required_positions = set(payload_positions[:RSA_SIGNATURE_PAYLOAD_BLOCK_COUNT])
    block_records: list[RsaSignatureBlock] = []
    chunks: list[bytes] = []
    missing_required: list[str] = []

    for sector, block in ordered_positions:
        block_data = blocks.get((sector, block))
        if block == TRAILER_BLOCK_INDEX:
            role = "mifare_sector_trailer"
        elif (sector, block) in required_positions:
            role = "rsa_signature_payload"
        else:
            role = "rsa_signature_region_extra"

        if block_data is None:
            block_records.append(
                RsaSignatureBlock(
                    sector=sector,
                    block=block,
                    absolute_block=sector * 4 + block,
                    role=role,
                    status="missing",
                    data_hex=None,
                    error=None,
                    included_in_signature_hex=False,
                )
            )
            if role == "rsa_signature_payload":
                missing_required.append(f"sector {sector} block {block}")
            continue

        include = role == "rsa_signature_payload" and block_data.data is not None and len(block_data.data) == BLOCK_SIZE_BYTES
        if include:
            assert block_data.data is not None
            chunks.append(block_data.data)
        elif role == "rsa_signature_payload":
            missing_required.append(block_data.source)

        block_records.append(
            RsaSignatureBlock(
                sector=block_data.sector,
                block=block_data.block,
                absolute_block=block_data.absolute_block,
                role=role,
                status=block_data.status,
                data_hex=block_data.data_hex,
                error=block_data.error,
                included_in_signature_hex=include,
            )
        )

    signature_bytes = b"".join(chunks)
    complete = not missing_required and len(signature_bytes) == RSA_SIGNATURE_EXPECTED_LENGTH_BYTES
    if not complete:
        result.warnings.append(
            "RSA signature data is partial; cryptographic verification was not performed."
        )

    return RsaSignature(
        status="complete" if complete else "partial",
        expected_length_bytes=RSA_SIGNATURE_EXPECTED_LENGTH_BYTES,
        available_length_bytes=len(signature_bytes),
        hex=signature_bytes.hex().upper(),
        verified=False,
        verification_status="not_implemented",
        blocks=block_records,
    )


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


def format_verbose(decoded: DecodedDump) -> str:
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
    conflict = catalogue_conflict(decoded)
    if conflict is not None:
        lines.extend(format_catalogue_conflict(conflict))
    if decoded.rsa_signature:
        lines.append("")
        lines.append("RSA signature:")
        lines.append(f"- status: {decoded.rsa_signature.status}")
        lines.append(
            f"- bytes: {decoded.rsa_signature.available_length_bytes}/"
            f"{decoded.rsa_signature.expected_length_bytes}"
        )
        lines.append(f"- verified: {decoded.rsa_signature.verified}")
        lines.append(f"- verification_status: {decoded.rsa_signature.verification_status}")
    if decoded.raw_unknown:
        lines.append("")
        lines.append("Preserved raw/unknown data:")
        for item in decoded.raw_unknown:
            lines.append(f"- {item.name}: {item.data_hex or '-'} ({item.source})")
    return "\n".join(lines)


def format_human_readable(decoded: DecodedDump) -> str:
    fields = {item.name: item.value for item in decoded.fields}
    signature = decoded.rsa_signature
    lines = [
        "Bambu RFID Filament Report",
        "",
        "Filament",
        "--------",
        report_line("Manufacturer", fields.get("manufacturer")),
        report_line("Product", fields.get("material_name")),
        report_line("Colour", fields.get("color_name")),
        report_line("Full name", fields.get("catalogue_name")),
        report_line("Catalogue match", format_catalogue_match(fields.get("catalogue_match_status"))),
        "",
        "Physical",
        "--------",
        report_line("Diameter", format_mm(fields.get("filament_diameter_mm"))),
        report_line("Nominal weight", format_grams(fields.get("spool_weight_grams"))),
        "",
        "Printing",
        "--------",
        report_line("Nozzle range", format_temperature_range(fields.get("hotend_min_temperature_c"), fields.get("hotend_max_temperature_c"))),
        report_line("Drying", format_drying(fields.get("drying_temperature_c"), fields.get("drying_time_hours"))),
        "",
        "RFID",
        "----",
        report_line("Tag UID", decoded.metadata.uid),
        report_line("Variant ID", fields.get("tray_info_variant_id")),
        report_line("Dump status", display_status(decoded.metadata.dump_status)),
        report_line("Signature", format_signature(signature)),
        report_line("Verified", "Yes" if signature and signature.verified else "No"),
    ]
    visible_warnings = [warning for warning in decoded.warnings if warning]
    if decoded.errors:
        lines.extend(["", "Errors", "------"])
        lines.extend(f"- {error}" for error in decoded.errors)
    if visible_warnings:
        lines.extend(["", "Warnings", "--------"])
        lines.extend(f"- {warning}" for warning in visible_warnings)
    return "\n".join(lines)


def catalogue_conflict(decoded: DecodedDump) -> dict[str, object] | None:
    for item in decoded.fields:
        if item.name == "catalogue_conflict" and isinstance(item.value, dict):
            return item.value
    return None


def format_catalogue_conflict(conflict: dict[str, object]) -> list[str]:
    differing_fields = conflict.get("differing_fields")
    downloaded = conflict.get("downloaded")
    bundled = conflict.get("bundled_fallback")
    if not isinstance(differing_fields, list) or not isinstance(downloaded, dict) or not isinstance(bundled, dict):
        return []

    lines = [
        "",
        "Catalogue conflict:",
        f"- Identifier: {conflict.get('identifier') or 'Unknown'}",
        f"- Differing fields: {', '.join(str(field) for field in differing_fields) or 'None'}",
        "",
        "Downloaded:",
    ]
    for field_name in differing_fields:
        lines.append(f"- {field_name}: {downloaded.get(field_name) if downloaded.get(field_name) is not None else 'Unknown'}")
    lines.append("")
    lines.append("Bundled fallback:")
    for field_name in differing_fields:
        lines.append(f"- {field_name}: {bundled.get(field_name) if bundled.get(field_name) is not None else 'Unknown'}")
    return lines


def report_line(label: str, value: object) -> str:
    shown = "Unknown" if value is None or value == "" else value
    return f"{label:<26}: {shown}"


def display_status(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "Unknown"
    return value.replace("_", " ").title()


def format_catalogue_match(value: object) -> str:
    status = display_status(value)
    return f"✓ {status}" if status == "Exact" else status


def format_mm(value: object) -> str:
    return f"{value:g} mm" if isinstance(value, (int, float)) else "Unknown"


def format_grams(value: object) -> str:
    return f"{value:g} g" if isinstance(value, (int, float)) else "Unknown"


def format_temperature_range(min_value: object, max_value: object) -> str:
    if isinstance(min_value, (int, float)) and isinstance(max_value, (int, float)):
        return f"{min_value:g}–{max_value:g} °C"
    return "Unknown"


def format_drying(temperature: object, hours: object) -> str:
    if isinstance(temperature, (int, float)) and isinstance(hours, (int, float)):
        return f"{temperature:g} °C for {hours:g} hours"
    return "Unknown"


def format_signature(signature: RsaSignature | None) -> str:
    if signature is None:
        return "Unknown"
    return f"{display_status(signature.status)} ({signature.available_length_bytes:g} bytes)"
