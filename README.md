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
