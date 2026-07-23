# Requirements

## Implemented

- Capture the Spoolman REST API schema from `http://localhost:7912/api/v1/openapi.json`.
- Validate the captured schema title and OpenAPI structure.
- Import 3D Filament Profiles CSV exports in dry-run or apply mode.
- Create a Spoolman backup before apply-mode import.
- Reuse existing Spoolman vendors and filaments where possible.
- Prevent duplicate spool imports using the original 3DFP spool UUID marker in the spool comment.
- Match PAX12 RFID payloads against Spoolman filaments and active spools.
- Bridge new PAX12 RFID log events from Moonraker to the local matcher.
- Run a standalone read-only Bambu RFID identifier proof of concept with CLI and PySide6 GUI entry points, plus mocked tests for reader selection, UID handling, GUI monitor events, authenticated memory inspection, block formatting, failure reporting, and JSON serialization.

## Agreed functional requirements

- 3D Filament Profiles remains the purchasing and master inventory system.
- Spoolman remains the operational spool database.
- TL3D Filament Manager is the workshop intelligence and UI layer.
- Inventory search must show the exact storage location of unopened spools.
- A spool can have only one current location.
- Scanning a spool into a new location automatically removes it from its old location.
- Tare weight must include a source: measured, manufacturer label, manufacturer default, or estimate.

## Location requirements

- Locations must support workshop storage.
- Locations must support garden stores.
- Locations must support racks.
- Locations may include optional positions, such as shelf, bay, column, row, or bin.

## RFID/NFC requirements

- RFID/NFC workflows use an ACS ACR1255U-J1 reader with NTAG215 tags.
- Genuine Bambu filament RFID memory inspection targets MIFARE Classic 1K tags and must remain read-only.
- Reusable-spool NFC tags belong to the physical spool.
- Cardboard spools can receive disposable NFC stickers.
- RFID scans must not silently select ambiguous matches.
- RFID proof-of-concept work must remain read-only unless writing is explicitly authorised.
- The standalone Bambu RFID identifier GUI must stay separate from the main TL3D Filament Manager GUI until integration is explicitly approved.
- Standalone Bambu RFID raw memory dumps must include reader name, UID, ATR, sector number, block number, raw hexadecimal data where readable, read status, and failure messages.
- Standalone Bambu RFID raw memory dumps must include schema version, creation timestamp, upstream reference, tag type where known, grouped sectors, grouped blocks, status/error data, and tool version.
- Authenticated Bambu memory reads must be started explicitly in the standalone identifier GUI and must not freeze the GUI.
- Saved Bambu RFID raw dump JSON files must be decodable without a reader connection.
- Decoding must report malformed JSON, unsupported schema versions, missing sectors or blocks, invalid hex data, unreadable blocks, and incomplete dumps without crashing.
- Unknown or undocumented Bambu RFID bytes must remain available as raw hex and must not be guessed.

## Future label-printing requirements

- Print through Windows-installed printers, initially the PM-241-BT.
- Support multiple saved label profiles.
- Support user-defined label width and height in millimetres.
- Support portrait and landscape orientation.
- Support adjustable margins and font sizes.
- Support separate layouts for large box labels, sealed-spool labels, rack labels, and NFC/location labels.
- Provide print preview and test print.
- Support individual and bulk printing.
- Generate labels from imported inventory data, not OCR.
- Include large readable manufacturer, material/product line, and colour text.
- Optionally include QR code, spool ID, and location.
- Do not hard-code label size or layout.

## Unresolved requirements

- Exact local persistence model for locations and label profiles.
- Exact NFC tag payload format.
- Exact QR code payload format for future labels.
