# Bambu RFID Identifier Proof Of Concept

Read-only PC/SC proof-of-concept for identifying tags with an ACS ACR1255U-J1 reader.

This tool is intentionally standalone and is not integrated into the TL3D Filament Manager GUI. It does not write, clone, or modify tags.

## What it does

- Lists all PC/SC reader names.
- Detects an ACS ACR1255U-J1 reader by name.
- Waits for a tag.
- Displays the tag ATR.
- Reads and displays the tag UID using the standard PC/SC `FF CA 00 00 00` GET DATA command.
- Detects tag removal.
- Avoids repeatedly reporting the same tag while it remains present.
- Reports missing readers, connection errors, and unsupported tags clearly.
- Provides a standalone PySide6 GUI with reader connection status, reader name, current status, UID, and ATR.
- Authenticates genuine Bambu MIFARE Classic 1K sectors with documented UID-derived keys and reads raw blocks without writing to the tag.
- Displays raw sector/block data and allows timestamped JSON dump saving.
- Decodes saved raw dump JSON files into documented Bambu fields without needing an RFID reader.

## Requirements

- Windows with Smart Card service running.
- ACS ACR1255U-J1 paired/connected and visible through PC/SC.
- Python 3.12 or later.
- `pyscard`.
- `PySide6`.

The ACS driver stack must expose the reader to PC/SC. If no readers are listed, fix Windows/driver/connection setup before debugging this script.

## Setup

From the project root:

```powershell
cd C:\Projects\TL3D-Filament-Manager
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\tools\bambu_rfid_identifier\requirements.txt
```

Or install directly:

```powershell
python -m pip install "pyscard>=2.0,<3"
```

## Usage

Run:

```powershell
python .\tools\bambu_rfid_identifier\identify_tag.py
```

The tool prints all PC/SC reader names, selects the first reader whose name contains `ACR1255U-J1`, then waits for a tag.

Use a different reader-name substring if Windows exposes the reader under a different name:

```powershell
python .\tools\bambu_rfid_identifier\identify_tag.py --reader-name ACR1255
```

Use any available reader for development:

```powershell
python .\tools\bambu_rfid_identifier\identify_tag.py --any-reader
```

Stop with `Ctrl+C`.

## GUI usage

Run the standalone PySide6 window:

```powershell
python .\tools\bambu_rfid_identifier\gui.py
```

Use a different reader-name substring if Windows exposes the reader under a different name:

```powershell
python .\tools\bambu_rfid_identifier\gui.py --reader-name ACR1255
```

Use any available reader for development:

```powershell
python .\tools\bambu_rfid_identifier\gui.py --any-reader
```

The GUI updates automatically when a tag is presented or removed. When a tag is removed, the status changes to `Tag removed` while the last successfully read UID and ATR remain visible for reference. UID and ATR are cleared when the reader monitor restarts, the reader disconnects, or a later successful tag read replaces them.

After a genuine Bambu tag UID is visible, click `Read Bambu Tag` to start an authenticated raw memory read. The read runs in a background Qt worker so the GUI remains responsive. Results are displayed by sector and block. `Save raw dump` is enabled after a read attempt produces dump data and writes a timestamped JSON file containing the reader name, UID, ATR, upstream reference, sector/block statuses, raw hex data where readable, and errors where unreadable.

The GUI reuses the same read-only PC/SC detection and UID-reading logic as `identify_tag.py`; it does not write, clone, emulate, change keys, change UIDs, or modify tags.

## Bambu memory inspection

Authenticated reads use the published `queengooborg/Bambu-Lab-RFID-Tag-Guide` research:

- `deriveKeys.py` for UID-based HKDF-SHA256 sector-key derivation.
- `docs/ReadTags.md` for the documented readout workflow.
- `docs/BambuLabRfid.md` for the raw block layout reference.

The implementation is an original Python standard-library implementation of the documented algorithm. It stores derived keys only in memory for the current read. Raw memory is displayed as hexadecimal blocks only; decoding material, colour, temperatures, and other filament fields is a later milestone.

## Decode a saved dump

Decode an existing raw dump without connecting the RFID reader:

```powershell
python -m tools.bambu_rfid_identifier.decode_dump path\to\bambu_rfid_dump.json
```

Print structured JSON instead of text:

```powershell
python -m tools.bambu_rfid_identifier.decode_dump path\to\bambu_rfid_dump.json --json
```

The decoder currently supports documented fields from `docs/BambuLabRfid.md`: tray/material IDs, filament type, detailed filament type, primary colour RGBA, spool weight, filament diameter, drying settings, bed/hotend temperatures, X Cam bytes, minimum nozzle diameter, tray UID, spool width, production date strings, and documented extra colour info. Filament diameter is decoded from sector 1 block 1 offset 8 as a 4-byte little-endian IEEE-754 float; this follows the upstream `float (LE)` type and real Bambu PLA Basic Blue dump validation. Unknown, reserved, MIFARE trailer, uncertain filament-length, and RSA signature bytes are preserved as raw hex for later analysis.

The decoder is read-only and works from saved JSON only. It does not generate, sign, modify, clone, or emulate tags.

## Development checks

The unit tests use mocked PC/SC objects and do not require a reader or tag:

```powershell
py -3.14 -m unittest discover -s .\tools\bambu_rfid_identifier -v
```

## Hardware Verification

Use `py -3.14` where available. Another supported Python 3 version may be used if it can install `pyscard` and access PC/SC.

Install dependencies:

```powershell
cd C:\Projects\TL3D-Filament-Manager
py -3.14 -m pip install -r .\tools\bambu_rfid_identifier\requirements.txt
```

Run automated checks:

```powershell
py -3.14 -m unittest discover -s .\tools\bambu_rfid_identifier -v
py -3.14 -m py_compile tools\bambu_rfid_identifier\identify_tag.py tools\bambu_rfid_identifier\memory_inspector.py tools\bambu_rfid_identifier\decoder.py tools\bambu_rfid_identifier\decode_dump.py tools\bambu_rfid_identifier\rfid_monitor.py tools\bambu_rfid_identifier\gui.py tools\bambu_rfid_identifier\test_identify_tag.py tools\bambu_rfid_identifier\test_memory_inspector.py tools\bambu_rfid_identifier\test_decoder.py tools\bambu_rfid_identifier\test_gui.py
```

Launch the reader diagnostic tool:

```powershell
py -3.14 .\tools\bambu_rfid_identifier\identify_tag.py
```

If Windows exposes the reader with a slightly different name:

```powershell
py -3.14 .\tools\bambu_rfid_identifier\identify_tag.py --reader-name ACR1255
```

Expected Phase 1 hardware result:

- the ACR1255U-J1 appears in the reader list
- the tool prints the tag ATR
- the tool prints the tag UID
- removing the tag prints a removal message
- keeping the same tag on the reader does not repeatedly print duplicate reads

## Roadmap

### Phase 1 - Reader diagnostics

- Detect ACR1255U-J1.
- Display available readers.
- Read ATR.
- Read UID.
- Detect tag removal.
- Suppress duplicate reads.
- Status: implemented, awaiting real hardware verification.

### Phase 2 - Bambu tag memory reading

- Derive required authentication keys from UID.
- Authenticate required sectors.
- Read tag memory using read-only commands.
- Display raw sector/block hex data.
- Save timestamped JSON dumps.
- Status: implemented, awaiting real hardware verification.

### Phase 3 - Bambu data decoding

- Decode documented raw dump fields from saved JSON.
- Preserve unknown and undocumented bytes.
- Status: implemented for documented fields and validated against one genuine PLA Basic Blue saved dump; broader real-world saved-dump validation pending.

### Phase 4 - Identifier window

- Present a large, clear result such as:

```text
PLA Basic
Jade White
```

- Must not rely on colour alone for status because the user is colour blind.
- Status: implemented, awaiting real hardware verification.

### Phase 5 - Main application integration

- Integrate only after the standalone tool is proven reliable.
- Status: future.

## Notes

- UID reading is read-only, but UID availability depends on the tag and PC/SC reader driver.
- NTAG215 tags should normally return a UID.
- Some unsupported or non-ISO14443 tags may provide an ATR but reject the UID command.
- This phase does not decode Bambu RFID payload data.
- This phase does not implement tag writing, tag cloning, or NFC assignment.
