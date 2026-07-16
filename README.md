# TL3D Filament Manager

Windows desktop application for managing filament inventory, importing 3D Filament Profiles data, integrating with Spoolman, and later resolving Bambu RFID data for Snapmaker U1/Paxx12.

## Initial setup

```powershell
cd C:\Projects\TL3D-Filament-Manager
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
python -m app
```

## Capture your Spoolman REST API schema

With Spoolman running at `http://localhost:7912`, capture the REST API v1 schema from
`http://localhost:7912/api/v1/openapi.json`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\capture_spoolman_schema.ps1
```

This creates:

```text
docs\spoolman-openapi.json
```

The script overwrites that file, verifies the response is an OpenAPI document for
the Spoolman REST API, and prints the detected API version and path count.

## Import 3D Filament Profiles CSV data

Run a dry-run first to validate the CSV and create JSON/TXT reports without
writing to Spoolman:

```powershell
python -m app.importers.three_dfp my-spools.csv --dry-run
```

Apply the import after reviewing the report:

```powershell
python -m app.importers.three_dfp my-spools.csv --apply
```

Both commands write timestamped reports to `import_reports\` by default. Spoolman
defaults to `http://localhost:7912`; override it when needed:

```powershell
python -m app.importers.three_dfp my-spools.csv --dry-run --spoolman-url http://spoolman.local:7912
```

## Run the local RFID matching service

Start the lightweight HTTP API. It binds to `0.0.0.0:8123` by default and uses
Spoolman at `http://localhost:7912`:

```powershell
python -m app.rfid_service
```

Override the Spoolman URL or port when needed:

```powershell
python -m app.rfid_service --spoolman-url http://spoolman.local:7912 --port 8123
```

Match a PAX12 RFID payload:

```powershell
curl.exe -X POST http://localhost:8123/api/rfid/match `
  -H "Content-Type: application/json" `
  -d '{"manufacturer":"Bambu Lab","material":"PLA","variant":"Basic","nums":1,"alpha":255,"mode":0,"colors":["0A2989"]}'
```

The response returns `status: "matched"` only when exactly one filament matches
vendor, material, variant, and colour. If more than one filament remains, the
service returns `status: "ambiguous"` with candidate filaments instead of
silently selecting one.

## Bridge PAX12 RFID log messages to the printer console

Run the RFID matcher first, then start the PAX12 bridge. The bridge polls
Moonraker's `klippy.log`, detects Bambu RFID lines, asks the local matcher for
the matching filament, and sends an `M118` console message back through
Moonraker.

```powershell
python -m app.rfid_service
python -m app.pax12_bridge --printer-url http://localhost:7125
```

The default printer URL is `http://localhost:7125` and can also be set with the
`TL3D_PRINTER_URL` environment variable. Override the matcher endpoint or poll
interval when needed:

```powershell
python -m app.pax12_bridge `
  --printer-url http://snapmaker.local:7125 `
  --matcher-url http://localhost:8123/api/rfid/match `
  --poll-seconds 2
```

The bridge processes only new log content and suppresses repeated RFID lines.
