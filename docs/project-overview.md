# Project Overview

## Purpose

TL3D Filament Manager is the workshop intelligence and user-interface layer for TL3D filament inventory. It connects purchasing records, operational spool state, RFID scans, and future label workflows without replacing the systems that already do those jobs well.

## Current implemented features

- Minimal PySide6 desktop shell.
- Spoolman REST API client based on the captured Spoolman OpenAPI schema.
- 3D Filament Profiles CSV importer with dry-run and apply modes.
- Import reports written as JSON and TXT.
- Local RFID matching HTTP service for PAX12/Bambu-style RFID payloads.
- PAX12 bridge that polls Moonraker `klippy.log` and sends matched filament messages back to the printer console.
- Standalone Bambu RFID identifier proof of concept for read-only PC/SC reader diagnostics and UID reading.

## Agreed system roles

- 3D Filament Profiles remains the purchasing and master inventory source.
- CSV exports from 3D Filament Profiles are imported into TL3D Filament Manager.
- Spoolman remains the operational spool database.
- TL3D Filament Manager provides workshop search, location intelligence, RFID workflows, and a desktop UI.
- PySide6 is the desktop interface framework.

## Near-term goal

Build a reliable local workflow for importing inventory, locating spools, identifying spools with RFID/NFC, and showing exact storage locations for unopened stock.

## Out of scope for now

- Replacing 3D Filament Profiles as the purchasing system.
- Replacing Spoolman as the operational spool database.
- Implementing label printing before core import, inventory, location, and RFID workflows are stable.
- Integrating RFID proof-of-concept code into the main GUI before hardware reading and decoding are proven.
