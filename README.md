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
