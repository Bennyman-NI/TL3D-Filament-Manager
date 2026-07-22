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
- `tools/bambu_rfid_identifier/` provides a standalone read-only PC/SC proof of concept for reader detection, ATR display, UID reading, tag removal, and duplicate-present suppression.

## Agreed hardware

- Reader: ACS ACR1255U-J1.
- Tags: NTAG215.

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
