# GUI Design

## Current implementation

The current GUI is a minimal PySide6 window with disabled placeholder actions for importing 3D Filament Profiles and completing Spoolman setup.

## Agreed direction

The desktop app should be practical workshop software: clear, dense enough for inventory work, and optimized for repeated lookup, scanning, importing, and printing tasks.

## Primary views

- Dashboard: Spoolman connection, recent imports, RFID service status, and quick search.
- Inventory search: manufacturer, material, colour, status, exact location, and unopened spool visibility.
- Import: CSV selection, dry-run summary, apply action, backup path, and report links.
- Locations: workshops, garden stores, racks, and optional positions.
- RFID/NFC: scan spool, assign tag, move spool, and resolve ambiguous matches.
- Labels: future profile selection, preview, test print, and bulk print.

## Inventory search expectations

- Search results must show exact storage location for unopened spools.
- Results should clearly separate available, opened, empty, archived, and unknown states.
- Spool movement should be visible as one current location, not a history list masquerading as current state.

## Import UX expectations

- Dry-run should be the default safe path.
- Apply mode should clearly show that a Spoolman backup will be created.
- Row-level errors should be visible without blocking valid rows.
- Reports should be easy to reopen after the import.

## Unresolved GUI decisions

- Final navigation structure.
- Whether location assignment is a modal, side panel, or full view.
- How much Spoolman editing belongs in TL3D versus linking back to Spoolman.
