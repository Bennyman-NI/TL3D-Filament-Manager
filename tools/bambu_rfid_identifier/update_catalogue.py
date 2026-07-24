from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

try:
    from . import catalogue_loader
except ImportError:  # pragma: no cover - supports direct script execution
    import catalogue_loader


USER_AGENT = "TL3D-Filament-Manager Bambu RFID Catalogue Updater/1.0"
NETWORK_TIMEOUT_SECONDS = 15
Urlopen = Callable[..., object]


@dataclass(frozen=True)
class UpdateResult:
    status: str
    dry_run: bool
    source_repository: str
    source_url: str
    cache_path: str
    metadata_path: str
    record_count: int
    added: int
    changed: int
    removed: int
    unchanged: int
    checksum: str | None
    fetched_at_utc: str | None
    etag: str | None
    last_modified: str | None
    error: str | None = None


def update_catalogue(
    *,
    dry_run: bool = False,
    force: bool = False,
    json_output: bool = False,
    cache_dir: Path = catalogue_loader.DEFAULT_CACHE_DIR,
    urlopen: Urlopen | None = None,
) -> UpdateResult:
    cache_path = cache_dir / "filaments.json"
    metadata_path = cache_dir / "metadata.json"
    opener = urlopen or urllib.request.urlopen
    metadata = catalogue_loader.read_metadata(metadata_path)
    request = build_request(force, metadata)

    try:
        response = opener(request, timeout=NETWORK_TIMEOUT_SECONDS)
        status_code = int(getattr(response, "status", 200))
        if status_code == 304:
            return unchanged_result(dry_run, cache_path, metadata_path, metadata)
        raw_bytes = response.read()
        headers = getattr(response, "headers", {})
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return unchanged_result(dry_run, cache_path, metadata_path, metadata)
        return error_result(dry_run, cache_path, metadata_path, f"HTTP error {exc.code}: {exc.reason}")
    except Exception as exc:
        return error_result(dry_run, cache_path, metadata_path, f"Download failed: {exc}")

    try:
        new_records = catalogue_loader.validate_catalogue_bytes(raw_bytes)
        old_records = load_existing_records(cache_path)
    except Exception as exc:
        return error_result(dry_run, cache_path, metadata_path, str(exc))

    diff = diff_records(old_records, {record.id: record for record in new_records})
    checksum = catalogue_loader.sha256_hex(raw_bytes)
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    etag = header_value(headers, "ETag")
    last_modified = header_value(headers, "Last-Modified")

    if not dry_run:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            write_atomic(cache_path, raw_bytes)
            metadata_payload = {
                "local_schema_version": catalogue_loader.LOCAL_SCHEMA_VERSION,
                "source_repository": catalogue_loader.SOURCE_REPOSITORY,
                "source_url": catalogue_loader.SOURCE_URL,
                "fetched_at_utc": fetched_at,
                "sha256": checksum,
                "record_count": len(new_records),
                "etag": etag,
                "last_modified": last_modified,
            }
            write_atomic(metadata_path, json.dumps(metadata_payload, indent=2).encode("utf-8") + b"\n")
        except OSError as exc:
            return error_result(dry_run, cache_path, metadata_path, f"Cache write failed: {exc}")

    return UpdateResult(
        status="updated",
        dry_run=dry_run,
        source_repository=catalogue_loader.SOURCE_REPOSITORY,
        source_url=catalogue_loader.SOURCE_URL,
        cache_path=str(cache_path),
        metadata_path=str(metadata_path),
        record_count=len(new_records),
        added=diff["added"],
        changed=diff["changed"],
        removed=diff["removed"],
        unchanged=diff["unchanged"],
        checksum=checksum,
        fetched_at_utc=fetched_at,
        etag=etag,
        last_modified=last_modified,
    )


def build_request(force: bool, metadata: dict[str, object]) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if not force:
        etag = metadata.get("etag")
        last_modified = metadata.get("last_modified")
        if isinstance(etag, str) and etag:
            headers["If-None-Match"] = etag
        if isinstance(last_modified, str) and last_modified:
            headers["If-Modified-Since"] = last_modified
    return urllib.request.Request(catalogue_loader.SOURCE_URL, headers=headers)


def load_existing_records(cache_path: Path) -> dict[str, catalogue_loader.CatalogueRecord]:
    try:
        return {record.id: record for record in catalogue_loader.validate_catalogue_bytes(cache_path.read_bytes())}
    except OSError:
        return {}


def diff_records(
    old_records: dict[str, catalogue_loader.CatalogueRecord],
    new_records: dict[str, catalogue_loader.CatalogueRecord],
) -> dict[str, int]:
    old_ids = set(old_records)
    new_ids = set(new_records)
    shared_ids = old_ids & new_ids
    return {
        "added": len(new_ids - old_ids),
        "removed": len(old_ids - new_ids),
        "changed": sum(1 for record_id in shared_ids if old_records[record_id].raw != new_records[record_id].raw),
        "unchanged": sum(1 for record_id in shared_ids if old_records[record_id].raw == new_records[record_id].raw),
    }


def write_atomic(path: Path, raw_bytes: bytes) -> None:
    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
        temp_name = handle.name
        handle.write(raw_bytes)
    os.replace(temp_name, path)


def header_value(headers: object, name: str) -> str | None:
    if hasattr(headers, "get"):
        value = headers.get(name)  # type: ignore[call-arg]
        return value if isinstance(value, str) else None
    return None


def unchanged_result(
    dry_run: bool,
    cache_path: Path,
    metadata_path: Path,
    metadata: dict[str, object],
) -> UpdateResult:
    return UpdateResult(
        status="up_to_date",
        dry_run=dry_run,
        source_repository=catalogue_loader.SOURCE_REPOSITORY,
        source_url=catalogue_loader.SOURCE_URL,
        cache_path=str(cache_path),
        metadata_path=str(metadata_path),
        record_count=int(metadata.get("record_count", 0)) if isinstance(metadata.get("record_count"), int) else 0,
        added=0,
        changed=0,
        removed=0,
        unchanged=0,
        checksum=metadata.get("sha256") if isinstance(metadata.get("sha256"), str) else None,
        fetched_at_utc=metadata.get("fetched_at_utc") if isinstance(metadata.get("fetched_at_utc"), str) else None,
        etag=metadata.get("etag") if isinstance(metadata.get("etag"), str) else None,
        last_modified=metadata.get("last_modified") if isinstance(metadata.get("last_modified"), str) else None,
    )


def error_result(dry_run: bool, cache_path: Path, metadata_path: Path, message: str) -> UpdateResult:
    return UpdateResult(
        status="error",
        dry_run=dry_run,
        source_repository=catalogue_loader.SOURCE_REPOSITORY,
        source_url=catalogue_loader.SOURCE_URL,
        cache_path=str(cache_path),
        metadata_path=str(metadata_path),
        record_count=0,
        added=0,
        changed=0,
        removed=0,
        unchanged=0,
        checksum=None,
        fetched_at_utc=None,
        etag=None,
        last_modified=None,
        error=message,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update the cached piitaya/bambu-filaments catalogue.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing cache files.")
    parser.add_argument("--force", action="store_true", help="Bypass conditional request headers, but still validate.")
    parser.add_argument("--json", action="store_true", help="Print structured JSON output.")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    urlopen: Urlopen | None = None,
    cache_dir: Path = catalogue_loader.DEFAULT_CACHE_DIR,
) -> int:
    args = parse_args(argv)
    result = update_catalogue(dry_run=args.dry_run, force=args.force, json_output=args.json, cache_dir=cache_dir, urlopen=urlopen)
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(format_result(result))
    return 1 if result.status == "error" else 0


def format_result(result: UpdateResult) -> str:
    lines = [
        "Bambu catalogue update",
        f"Status: {result.status}",
        f"Records: {result.record_count}",
        f"Added: {result.added}",
        f"Changed: {result.changed}",
        f"Removed: {result.removed}",
        f"Unchanged: {result.unchanged}",
        f"Cache: {result.cache_path}",
    ]
    if result.error:
        lines.append(f"Error: {result.error}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
