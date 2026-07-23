# RFID Design

## Current implemented behavior

- `app/rfid_service.py` exposes `POST /api/rfid/match`.
- The matcher queries Spoolman filaments and active spools.
- Hex colours are normalized by removing `#` and converting to uppercase.
- Matching uses vendor, material, variant contained in filament name, and exact colour data.
- Ambiguous matches return candidates instead of silently selecting one.
- `app/pax12_bridge.py` polls Moonraker `klippy.log` for PAX12 RFID lines.
- Historical RFID lines are ignored on bridge startup.
- Immediate duplicate events are suppressed with a configurable cooldown.
- Matched RFID events are sent to the printer console through Moonraker.
- `tools/bambu_rfid_identifier/` provides a standalone read-only PC/SC proof of concept for reader detection, ATR display, UID reading, tag removal, duplicate-present suppression, authenticated Bambu MIFARE Classic 1K memory inspection, timestamped JSON dumps, and a live PySide6 identifier window.

## Agreed hardware

- Reader: ACS ACR1255U-J1.
- TL3D-owned NFC tags: NTAG215.
- Genuine Bambu spool RFID tags inspected by the standalone proof of concept: MIFARE Classic 1K.

## Bambu tag memory inspection

- Key derivation follows the public `queengooborg/Bambu-Lab-RFID-Tag-Guide` `deriveKeys.py` algorithm: HKDF-SHA256 using the tag UID, the documented 16-byte salt, and the `RFID-A\0` / `RFID-B\0` contexts.
- The raw block map reference is `docs/BambuLabRfid.md`; readout workflow context comes from `docs/ReadTags.md`.
- The standalone tool loads derived Key A values into the reader session, authenticates sectors with Key A, and reads blocks with PC/SC read commands.
- The tool records authentication failures, unreadable blocks, reader errors, and partial reads per block.
- Manufacturer blocks and sector trailers are included in the table and JSON dump when readable, but the tool never writes to any tag block.
- The GUI starts raw reads only from the standalone tool's `Read Bambu Tag` button and runs the dump worker off the UI thread.
- See `docs/rfid-references.md` for source and licence notes.

## Saved dump decoding

- `tools/bambu_rfid_identifier/decoder.py` decodes saved raw dump JSON files without an RFID reader.
- `tools/bambu_rfid_identifier/decode_dump.py` provides `python -m tools.bambu_rfid_identifier.decode_dump path\to\dump.json` with text output and optional `--json`.
- The decoder supports only documented fields from `docs/BambuLabRfid.md`, including tray/material IDs, filament type, detailed filament type, colour RGBA, spool weight, filament diameter, drying settings, temperature settings, X Cam bytes, minimum nozzle diameter, tray UID, spool width, production date strings, and extra colour info.
- Unknown, reserved, uncertain filament-length, MIFARE trailer, and RSA signature bytes remain preserved as raw hex.
- The decoder does not generate signatures, bypass signatures, create tags, modify tags, or integrate decoded data into Spoolman or the main TL3D GUI.

## Tag ownership rules

- Reusable-spool NFC tags belong to the physical spool.
- Cardboard spools can receive disposable NFC stickers.
- A tag assignment should resolve to one physical spool whenever possible.

## Spool movement rule

Scanning a spool into a new location automatically removes it from its old location. TL3D should treat the scanned location as the spool's current location.

## Matching principles

- Do not silently choose among ambiguous filament or spool matches.
- Keep RFID matching explainable to the user.
- Preserve external IDs and source markers where supported.
- Use Spoolman as the operational spool source.
- Keep proof-of-concept RFID work read-only unless writing is explicitly authorised.
- Do not rely on colour alone in RFID result displays.

## Future RFID workflows

- Assign NFC tag to spool.
- Scan spool to view current location and remaining weight.
- Scan location tag, then spool tag, to move inventory.
- Support bulk location intake for new unopened spools.
- Show warnings when the scanned tag points to an archived or missing spool.

## Unresolved decisions

- NFC payload format.
- Whether location tags use the same NTAG215 format as spool tags.
- Whether TL3D writes tag IDs into Spoolman comments, a local database, or both.
