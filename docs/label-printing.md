# Label Printing

## Status

Label printing is a future roadmap phase. It should come after core inventory, import, location, and RFID features are stable.

## Agreed design

- Print through Windows-installed printers.
- Initial target printer: PM-241-BT.
- Support multiple saved label profiles.
- Label profiles define width and height in millimetres.
- Profiles support portrait or landscape orientation.
- Profiles support adjustable margins and font sizes.
- Label size and layout must not be hard-coded.
- Labels are generated from imported inventory data, not OCR.

## Label types

- Large box labels.
- Smaller sealed-spool labels.
- Rack labels.
- NFC/location labels.

## Content

Labels should emphasize large, readable text for:

- manufacturer
- material or product line
- colour name

Optional fields:

- QR code
- spool ID
- exact location
- purchase or import reference

## User workflow

- Choose one or more inventory records.
- Select a saved label profile.
- Preview the label.
- Run a test print.
- Print one label or bulk labels.

## Unresolved decisions

- Label profile file format.
- QR code payload format.
- Whether print preview is rendered with Qt, PDF, or an image canvas.
- Whether profiles are global, per-printer, or per-label-type.
