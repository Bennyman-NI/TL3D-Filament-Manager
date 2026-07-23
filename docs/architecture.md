# Architecture

## Current components

- `app/__main__.py`: minimal PySide6 desktop entry point.
- `app/spoolman_client.py`: typed Spoolman REST API client.
- `app/importers/three_dfp.py`: 3D Filament Profiles CSV importer.
- `app/rfid_service.py`: local HTTP RFID matcher at `/api/rfid/match`.
- `app/pax12_bridge.py`: Moonraker log bridge for PAX12 RFID events.
- `scripts/capture_spoolman_schema.ps1`: captures and validates the Spoolman OpenAPI schema.
- `tools/bambu_rfid_identifier/`: standalone read-only PC/SC proof of concept for ACR1255U-J1 reader diagnostics, Bambu RFID raw memory dumping, timestamped JSON dumps, and CLI/PySide6 GUI entry points.

## Data flow

1. 3D Filament Profiles tracks purchases and master inventory.
2. User exports CSV from 3D Filament Profiles.
3. TL3D imports the CSV, creates or reuses Spoolman vendors, filaments, and spools.
4. Spoolman stores operational spool records, weights, colour data, and locations.
5. RFID services query Spoolman through `SpoolmanClient`.
6. The desktop UI will present search, location, import, RFID, and label workflows.

## External systems

- Spoolman: operational spool database, default URL `http://localhost:7912`.
- Moonraker: printer API used by the PAX12 bridge, default URL `http://localhost:7125`.
- Snapmaker U1/PAX12 logs: source of RFID events.
- Windows printer subsystem: future label-printing target.

## Design constraints

- Use only fields present in the captured Spoolman OpenAPI schema for Spoolman writes.
- Do not store unregistered custom fields in Spoolman create requests.
- Preserve original 3D Filament Profiles spool UUIDs in comments for duplicate detection.
- Keep source-of-truth boundaries clear: purchasing in 3D Filament Profiles, operations in Spoolman, workflow intelligence in TL3D.
- Keep RFID proof-of-concept work standalone and read-only unless broader integration or writing is explicitly approved.

## Unresolved architecture decisions

- Whether TL3D should persist its own local database or derive most state from Spoolman plus import reports.
- How the main desktop UI will coordinate long-running imports and RFID scans after standalone RFID hardware verification.
- Whether future label templates are stored as JSON, SQLite rows, or another local profile format.
