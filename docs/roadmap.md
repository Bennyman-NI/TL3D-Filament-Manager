# Roadmap

## Implemented foundation

- Spoolman schema capture.
- Spoolman client.
- 3D Filament Profiles CSV importer.
- Import reports.
- Local RFID matcher.
- PAX12 Moonraker log bridge.
- Minimal PySide6 application shell.
- Standalone Bambu RFID identifier CLI and PySide6 GUI proof of concept.
- Standalone read-only Bambu RFID memory inspection with raw sector/block hex dumps.

## Phase 1: Core inventory workflow

- Build the desktop import UI.
- Show import reports in the app.
- Add inventory search backed by Spoolman.
- Show exact current location for unopened spools.
- Add structured location management.

## Phase 2: RFID and location operations

- Verify the standalone Bambu RFID identifier proof of concept with real ACR1255U-J1 hardware.
- Integrate the ACS ACR1255U-J1 reader after standalone proof-of-concept hardware verification.
- Read NTAG215 spool tags.
- Assign reusable-spool tags to physical spools.
- Support disposable NFC stickers for cardboard spools.
- Move spools by scanning location and spool tags.
- Resolve ambiguous scans through the GUI.

## RFID proof-of-concept milestone

- PC/SC reader detection: implemented in code and verified by automated tests where practical; awaiting real ACR1255U-J1 hardware verification.
- ATR and UID reading: implemented in code and verified by automated tests with mocked PC/SC objects; awaiting real tag hardware verification.
- Standalone identifier window: implemented in code and verified by automated tests with mocked PC/SC objects; awaiting real tag hardware verification.
- Bambu sector authentication and raw memory inspection: implemented in code and verified by automated tests with mocked PC/SC objects; awaiting real ACR1255U-J1 and genuine Bambu tag hardware verification.
- Real ACR1255U-J1 hardware verification: awaiting user hardware test.
- Bambu tag decoding beyond raw hexadecimal block display: not started.
- Later main application integration: future; do not integrate until the standalone tool is proven reliable.

## Phase 3: Workshop intelligence

- Identify low stock and duplicate colours.
- Highlight missing or stale location data.
- Compare 3D Filament Profiles imports with Spoolman state.
- Add practical dashboards for workshop storage and active spools.

## Phase 4: Label printing

- Add Windows printer support, initially for the PM-241-BT.
- Add saved label profiles.
- Add configurable label dimensions, orientation, margins, and font sizes.
- Add print preview, test print, individual printing, and bulk printing.
- Add layouts for boxes, sealed spools, racks, and NFC/location labels.

## Later ideas

- Better Snapmaker Orca integration for friendly colour labels.
- Optional TL3D local API for slicer and workshop tools.
- Location history and audit trail.
- Advanced stock planning based on usage and purchases.
- Shopify integration.
