from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from . import identify_tag
except ImportError:  # pragma: no cover - supports direct script execution
    import identify_tag


SCHEMA_VERSION = 1
TOOL_VERSION = "tl3d-bambu-rfid-identifier-0.1"
UPSTREAM_PROJECT = "Bambu-Lab-RFID-Tag-Guide"
UPSTREAM_URL = "https://github.com/queengooborg/Bambu-Lab-RFID-Tag-Guide"
UPSTREAM_LICENSE = "GPL-3.0"
UPSTREAM_FILES = {
    "LICENSE": f"{UPSTREAM_URL}/blob/main/LICENSE",
    "deriveKeys.py": f"{UPSTREAM_URL}/blob/main/deriveKeys.py",
    "docs/ReadTags.md": f"{UPSTREAM_URL}/blob/main/docs/ReadTags.md",
    "docs/BambuLabRfid.md": f"{UPSTREAM_URL}/blob/main/docs/BambuLabRfid.md",
}
BAMBU_MASTER_KEY = bytes.fromhex("9A759CF2C4F7CAFF222CB9769B41BC96")
KEY_A_CONTEXT = b"RFID-A\0"
KEY_B_CONTEXT = b"RFID-B\0"
MIFARE_CLASSIC_1K_SECTORS = 16
MIFARE_CLASSIC_BLOCKS_PER_SECTOR = 4
MIFARE_CLASSIC_BLOCK_SIZE = 16
PCSC_SUCCESS = (0x90, 0x00)
SUPPORTED_UID_BYTE_LENGTHS = {4, 7, 10}
WRITE_APDU_PREFIXES = {(0xFF, 0xD6)}


class BambuDumpError(Exception):
    pass


@dataclass(frozen=True)
class BambuSectorKeys:
    key_a: bytes
    key_b: bytes


@dataclass(frozen=True)
class BlockDump:
    block: int
    absolute_block: int
    status: str
    data_hex: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SectorDump:
    sector: int
    authentication_status: str
    blocks: list[BlockDump]
    error: str | None = None


@dataclass(frozen=True)
class RawDump:
    schema_version: int
    created_at: str
    reader_name: str
    uid: str
    atr: str
    tag_type: str
    upstream_reference: dict[str, object]
    sectors: list[SectorDump]
    status: str
    error: str | None
    software: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BambuMemoryInspector:
    def inspect_card(self, card: object, pcsc: identify_tag.PcscApi, identity: identify_tag.TagIdentity) -> RawDump:
        reader_name = str(getattr(card, "reader", identity.reader_name))
        uid_hex = identity.uid or ""

        try:
            uid = validate_uid_hex(uid_hex)
        except ValueError as exc:
            return raw_dump_with_error(
                reader_name=reader_name,
                uid=uid_hex,
                atr=identity.atr,
                status="unsupported_tag",
                message=str(exc),
            )

        keys = derive_bambu_sector_keys(uid)

        try:
            connection = card.createConnection()
        except AttributeError:
            return raw_dump_with_error(
                reader_name=reader_name,
                uid=uid_hex,
                atr=identity.atr,
                status="reader_error",
                message="Unsupported card object from pyscard.",
            )

        sectors: list[SectorDump] = []
        overall_status = "success"
        overall_error: str | None = None

        try:
            connect_card(connection, pcsc)
            for sector in range(MIFARE_CLASSIC_1K_SECTORS):
                try:
                    sectors.append(read_sector(connection, sector, keys[sector]))
                except pcsc.no_card_exception as exc:
                    sectors.append(failed_sector(sector, "tag_removed", f"Tag removed during read: {exc}"))
                    overall_status = "partial"
                    overall_error = "Tag removed during read."
                    break
                except pcsc.card_connection_exception as exc:
                    sectors.append(failed_sector(sector, "reader_error", f"Reader disconnected during read: {exc}"))
                    overall_status = "partial"
                    overall_error = "Reader disconnected during read."
                    break
        except pcsc.no_card_exception as exc:
            return raw_dump_with_error(reader_name, uid_hex, identity.atr, "tag_removed", f"Tag removed before read: {exc}")
        except pcsc.card_connection_exception as exc:
            return raw_dump_with_error(reader_name, uid_hex, identity.atr, "reader_error", f"Reader error before read: {exc}")
        finally:
            identify_tag.disconnect_quietly(connection)

        if any(sector.authentication_status != "success" for sector in sectors):
            overall_status = "partial"
        if any(block.status != "success" for sector in sectors for block in sector.blocks):
            overall_status = "partial"

        return RawDump(
            schema_version=SCHEMA_VERSION,
            created_at=utc_timestamp(),
            reader_name=reader_name,
            uid=uid_hex,
            atr=identity.atr,
            tag_type="MIFARE Classic 1K (assumed from Bambu workflow)",
            upstream_reference=upstream_reference(),
            sectors=sectors,
            status=overall_status,
            error=overall_error,
            software={"tool": TOOL_VERSION},
        )


def validate_uid_hex(uid_hex: str) -> bytes:
    normalized = uid_hex.strip().replace(" ", "").replace(":", "").upper()
    if not normalized:
        raise ValueError("UID is required for Bambu key derivation.")
    if not re.fullmatch(r"[0-9A-F]+", normalized):
        raise ValueError("UID must contain only hexadecimal characters.")
    if len(normalized) % 2:
        raise ValueError("UID hexadecimal length must be even.")

    uid = bytes.fromhex(normalized)
    if len(uid) not in SUPPORTED_UID_BYTE_LENGTHS:
        allowed = ", ".join(str(length) for length in sorted(SUPPORTED_UID_BYTE_LENGTHS))
        raise ValueError(f"Unsupported UID length: {len(uid)} bytes. Expected one of: {allowed}.")
    return uid


def derive_bambu_sector_keys(uid: bytes) -> list[BambuSectorKeys]:
    key_a_values = hkdf_sha256(uid, length=6, salt=BAMBU_MASTER_KEY, info=KEY_A_CONTEXT, count=MIFARE_CLASSIC_1K_SECTORS)
    key_b_values = hkdf_sha256(uid, length=6, salt=BAMBU_MASTER_KEY, info=KEY_B_CONTEXT, count=MIFARE_CLASSIC_1K_SECTORS)
    return [
        BambuSectorKeys(key_a=key_a_values[index], key_b=key_b_values[index])
        for index in range(MIFARE_CLASSIC_1K_SECTORS)
    ]


def hkdf_sha256(input_key_material: bytes, *, length: int, salt: bytes, info: bytes, count: int) -> list[bytes]:
    prk = hmac.new(salt, input_key_material, hashlib.sha256).digest()
    okm = b""
    previous = b""
    for index in range(1, count + 1):
        previous = hmac.new(prk, previous + info + bytes([index]), hashlib.sha256).digest()
        okm += previous

    return [okm[offset : offset + length] for offset in range(0, length * count, length)]


def connect_card(connection: object, pcsc: identify_tag.PcscApi) -> None:
    try:
        connection.connect(pcsc.card_connection.T1_protocol)
    except (pcsc.card_connection_exception, pcsc.no_card_exception):
        connection.connect()


def read_sector(connection: object, sector: int, sector_keys: BambuSectorKeys) -> SectorDump:
    auth_error = load_key_and_authenticate_sector(connection, sector, sector_keys.key_a)
    if auth_error is not None:
        return failed_sector(sector, "authentication_failed", auth_error)

    return SectorDump(
        sector=sector,
        authentication_status="success",
        blocks=[read_block(connection, sector, block) for block in range(MIFARE_CLASSIC_BLOCKS_PER_SECTOR)],
    )


def load_key_and_authenticate_sector(connection: object, sector: int, key_a: bytes) -> str | None:
    load_data, load_sw1, load_sw2 = transmit_read_only(connection, load_key_apdu(key_a))
    if (load_sw1, load_sw2) != PCSC_SUCCESS:
        return format_status("key_load_failed", load_sw1, load_sw2, load_data)

    first_block = absolute_block_number(sector, 0)
    auth_data, auth_sw1, auth_sw2 = transmit_read_only(connection, authenticate_key_a_apdu(first_block))
    if (auth_sw1, auth_sw2) != PCSC_SUCCESS:
        return format_status("authentication_failed", auth_sw1, auth_sw2, auth_data)

    return None


def read_block(connection: object, sector: int, block: int) -> BlockDump:
    absolute_block = absolute_block_number(sector, block)
    data, sw1, sw2 = transmit_read_only(connection, read_binary_apdu(absolute_block))
    if (sw1, sw2) != PCSC_SUCCESS:
        return BlockDump(
            block=block,
            absolute_block=absolute_block,
            status="read_failed",
            error=format_status("read_failed", sw1, sw2, data),
        )

    data_hex = identify_tag.bytes_to_hex(data)
    if len(data) != MIFARE_CLASSIC_BLOCK_SIZE:
        return BlockDump(
            block=block,
            absolute_block=absolute_block,
            status="read_warning",
            data_hex=data_hex,
            error=f"Read returned {len(data)} bytes instead of {MIFARE_CLASSIC_BLOCK_SIZE}.",
        )

    return BlockDump(block=block, absolute_block=absolute_block, status="success", data_hex=data_hex)


def failed_sector(sector: int, status: str, message: str) -> SectorDump:
    return SectorDump(
        sector=sector,
        authentication_status=status,
        error=message,
        blocks=[
            BlockDump(
                block=block,
                absolute_block=absolute_block_number(sector, block),
                status=status,
                error=message,
            )
            for block in range(MIFARE_CLASSIC_BLOCKS_PER_SECTOR)
        ],
    )


def raw_dump_with_error(reader_name: str, uid: str, atr: str, status: str, message: str) -> RawDump:
    return RawDump(
        schema_version=SCHEMA_VERSION,
        created_at=utc_timestamp(),
        reader_name=reader_name,
        uid=uid,
        atr=atr,
        tag_type="unknown",
        upstream_reference=upstream_reference(),
        sectors=[],
        status=status,
        error=message,
        software={"tool": TOOL_VERSION},
    )


def load_key_apdu(key: bytes, *, key_slot: int = 0) -> list[int]:
    if len(key) != 6:
        raise ValueError("MIFARE Classic keys must be exactly 6 bytes.")
    return [0xFF, 0x82, 0x00, key_slot, 0x06, *key]


def authenticate_key_a_apdu(absolute_block: int, *, key_slot: int = 0) -> list[int]:
    return [0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, absolute_block, 0x60, key_slot]


def read_binary_apdu(absolute_block: int) -> list[int]:
    return [0xFF, 0xB0, 0x00, absolute_block, MIFARE_CLASSIC_BLOCK_SIZE]


def transmit_read_only(connection: object, apdu: list[int]) -> tuple[list[int], int, int]:
    if len(apdu) >= 2 and tuple(apdu[:2]) in WRITE_APDU_PREFIXES:
        raise BambuDumpError(f"Refusing write-like APDU: {identify_tag.bytes_to_hex(apdu)}")
    return connection.transmit(apdu)


def absolute_block_number(sector: int, block: int) -> int:
    return sector * MIFARE_CLASSIC_BLOCKS_PER_SECTOR + block


def format_status(status: str, sw1: int, sw2: int, data: Iterable[int]) -> str:
    data_hex = identify_tag.bytes_to_hex(data)
    suffix = f"; response data {data_hex}" if data_hex else ""
    return f"{status}. Status: {sw1:02X} {sw2:02X}{suffix}"


def upstream_reference() -> dict[str, object]:
    return {
        "project": UPSTREAM_PROJECT,
        "url": UPSTREAM_URL,
        "license": UPSTREAM_LICENSE,
        "files_consulted": UPSTREAM_FILES,
        "implementation": "Original stdlib implementation based on the documented algorithm; no upstream code copied.",
    }


def save_memory_dump(dump: RawDump, output_dir: Path | str = "rfid_dumps") -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_uid = dump.uid or "unknown_uid"
    path = target_dir / f"bambu_rfid_dump_{safe_uid}_{filename_timestamp()}.json"
    path.write_text(json.dumps(dump.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def filename_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_dump_lines(dump: RawDump) -> list[str]:
    lines = [
        f"Reader: {dump.reader_name}",
        f"UID: {dump.uid}",
        f"ATR: {dump.atr or 'unavailable'}",
        f"Status: {dump.status}",
    ]
    if dump.error:
        lines.append(f"Error: {dump.error}")

    for sector in dump.sectors:
        lines.append(f"Sector {sector.sector:02d}: {sector.authentication_status}")
        if sector.error:
            lines.append(f"  Error: {sector.error}")
        for block in sector.blocks:
            data = block.data_hex if block.data_hex is not None else "-"
            error = f" ({block.error})" if block.error else ""
            lines.append(f"  Block {block.block} absolute {block.absolute_block:02d} {block.status}: {data}{error}")
    return lines


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display a saved read-only Bambu RFID raw dump JSON file.")
    parser.add_argument("json_file", type=Path, help="Saved Bambu RFID memory dump JSON file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    sectors = [
        SectorDump(
            sector=sector["sector"],
            authentication_status=sector["authentication_status"],
            error=sector.get("error"),
            blocks=[BlockDump(**block) for block in sector["blocks"]],
        )
        for sector in payload["sectors"]
    ]
    dump = RawDump(
        schema_version=payload["schema_version"],
        created_at=payload["created_at"],
        reader_name=payload["reader_name"],
        uid=payload["uid"],
        atr=payload["atr"],
        tag_type=payload["tag_type"],
        upstream_reference=payload["upstream_reference"],
        sectors=sectors,
        status=payload["status"],
        error=payload.get("error"),
        software=payload["software"],
    )
    print("\n".join(format_dump_lines(dump)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
