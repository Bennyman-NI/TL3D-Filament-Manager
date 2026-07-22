# Inventory And Locations

## System roles

- 3D Filament Profiles is the purchasing and master inventory system.
- TL3D imports CSV exports from 3D Filament Profiles.
- Spoolman stores operational spool records.
- TL3D adds workshop search, location workflows, RFID/NFC workflows, and reporting.

## Current implemented behavior

- The importer reads real 3D Filament Profiles CSV headers.
- Vendors and filaments are reused when possible.
- Spools are created in Spoolman with the original 3DFP spool UUID marker in the spool comment.
- Imported spools use `initial_weight=1000` and map `remaining_grams` to `remaining_weight`.
- Empty spool weight is mapped separately to Spoolman `spool_weight`.

## Agreed inventory model

- A physical spool has one current location.
- Moving or scanning a spool into a new location automatically removes it from the old location.
- Unopened spool search must show the exact storage location.
- Tare weight must include its source:
  - measured
  - manufacturer label
  - manufacturer default
  - estimate

## Location model

Locations should support:

- workshop
- garden stores
- racks
- optional positions such as shelf, row, bay, column, box, or bin

## Practical examples

- `Workshop / Rack A / Shelf 2`
- `Garden Store 1 / Box PLA-03`
- `Workshop / Dry Box / Slot 4`
- `Rack B / Bay 5`

## Unresolved decisions

- Whether current location is stored only in Spoolman `spool.location` or mirrored in a TL3D local store.
- Whether location history is required.
- Exact schema for structured locations and positions.
- How unopened spool status is inferred when 3D Filament Profiles and Spoolman disagree.
