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

## Requirements

- Windows with Smart Card service running.
- ACS ACR1255U-J1 paired/connected and visible through PC/SC.
- Python 3.12 or later.
- `pyscard`.

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
py -3.14 -m py_compile tools\bambu_rfid_identifier\identify_tag.py tools\bambu_rfid_identifier\test_identify_tag.py
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
- Status: not started.

### Phase 3 - Bambu data decoding

- Decode product family.
- Decode material.
- Decode colour.
- Decode other useful spool metadata.
- Status: not started.

### Phase 4 - Identifier window

- Present a large, clear result such as:

```text
PLA Basic
Jade White
```

- Must not rely on colour alone for status because the user is colour blind.
- Status: not started.

### Phase 5 - Main application integration

- Integrate only after the standalone tool is proven reliable.
- Status: future.

## Notes

- UID reading is read-only, but UID availability depends on the tag and PC/SC reader driver.
- NTAG215 tags should normally return a UID.
- Some unsupported or non-ISO14443 tags may provide an ATR but reject the UID command.
- This phase does not decode Bambu RFID payload data.
- This phase does not implement tag writing, tag cloning, or NFC assignment.
