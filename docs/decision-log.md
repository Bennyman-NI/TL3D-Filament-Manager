# Decision Log

## 2026-07-17: System roles

Decision: 3D Filament Profiles remains the purchasing and master inventory system, Spoolman remains the operational spool database, and TL3D Filament Manager becomes the workshop intelligence and user-interface layer.

Reason: This preserves existing strengths while allowing TL3D to focus on import, search, location, RFID, and workflow improvements.

Status: Agreed design.

## 2026-07-17: Desktop framework

Decision: Use PySide6 for the desktop interface.

Reason: The project already depends on PySide6 and has a minimal PySide6 app shell.

Status: Implemented foundation.

## 2026-07-17: RFID hardware and tags

Decision: Use an ACS ACR1255U-J1 reader with NTAG215 tags. Reusable-spool NFC tags belong to the physical spool; cardboard spools may use disposable NFC stickers.

Reason: The design needs a clear tag ownership model that works for durable reusable spools and temporary cardboard spools.

Status: Agreed design.

## 2026-07-17: Single current location

Decision: A spool can have only one current location. Scanning it into a new location automatically removes it from its old location.

Reason: Inventory search must answer where the spool is now without making the user interpret movement history.

Status: Agreed design.

## 2026-07-17: Custom label profiles

Decision: Label printing will use saved custom label profiles with user-defined width, height, orientation, margins, font sizes, and layout per label type.

Reason: The PM-241-BT and future printers may use different stock sizes. Box labels, sealed-spool labels, rack labels, and NFC/location labels need different layouts. Hard-coded sizes would make the feature brittle.

Status: Future roadmap.

## 2026-07-22: Standalone Bambu RFID identifier

Decision: The Bambu RFID identifier remains a standalone proof-of-concept tool until hardware reading and decoding are proven reliable.

Reason: Reader diagnostics, UID reading, authentication research, and decoding need hardware verification before they are safe to fold into the main TL3D desktop workflow.

Status: Agreed scope.

## 2026-07-22: RFID work is read-only

Decision: RFID proof-of-concept work remains read-only. Tag writing, cloning, emulation, or tag modification must not be implemented unless explicitly authorised.

Reason: The current milestone is identification and diagnostics. Writing or emulation would add safety, legal, and data-integrity risks outside the approved scope.

Status: Active constraint.

## 2026-07-22: RFID interface cannot rely on colour alone

Decision: RFID identification results must not depend on colour alone because the user is colour blind.

Reason: The interface needs large, clear text such as material, product line, and colour name, with colour swatches as supporting context only.

Status: Agreed design.

## 2026-07-22: Documentation and roadmap upkeep

Decision: Relevant Codex tasks must update documentation and roadmap status when project status, scope, or milestones change.

Reason: The project is evolving through focused tasks, so README and `/docs` need to remain the reliable source of current design and implementation status.

Status: Active process rule.

## 2026-07-23: Standalone RFID GUI uses existing read-only logic

Decision: The Bambu RFID identifier GUI is a standalone PySide6 tool under `tools/bambu_rfid_identifier/` and reuses the existing PC/SC reader selection, card observer, and UID-read logic from `identify_tag.py`.

Reason: This gives live reader and tag status without integrating RFID proof-of-concept behavior into the main TL3D Filament Manager GUI or duplicating RFID operations.

Status: Implemented in code; awaiting real hardware verification.

## 2026-07-23: Standard Codex completion reports

Decision: Codex implementation tasks should end with a structured completion report covering changes, file additions/modifications/deletions, tests run or skipped, manual verification needs, limitations, follow-ups, and a suggested commit message.

Reason: Consistent completion reports make review easier and keep hardware, testing, and commit readiness visible.

Status: Active process rule.

## 2026-07-23: Read-only Bambu RFID memory inspection

Decision: The standalone Bambu RFID identifier may derive public Bambu sector keys using the documented `queengooborg/Bambu-Lab-RFID-Tag-Guide` algorithm and read raw MIFARE Classic 1K blocks, but it must not write, clone, emulate, brute-force, or modify tags.

Reason: Raw authenticated reads are needed to compare genuine Bambu tags while preserving the safety boundary around RFID proof-of-concept work.

Status: Implemented in code with mocked tests; awaiting real Bambu tag hardware verification.

## 2026-07-23: Saved Bambu RFID dumps decode separately from scanning

Decision: Bambu RFID field decoding is implemented as a reusable saved-dump decoder separate from the RFID reader, standalone GUI, Spoolman, inventory workflows, and the main TL3D GUI.

Reason: Decoding saved JSON files keeps the workflow read-only, allows validation without hardware, and avoids coupling uncertain tag-field work to operational inventory features.

Status: Implemented for documented fields with synthetic tests; awaiting validation against real saved dumps.

## 2026-07-23: Bambu filament diameter is decoded as float32

Decision: The saved-dump decoder reads filament diameter from sector 1 block 1, offset 8 as a 4-byte little-endian IEEE-754 float.

Reason: The upstream Bambu RFID layout marks the field as `float (LE)` but lists length `8`. Validation against a genuine Bambu PLA Basic Blue dump showed bytes `00 00 E0 3F` at the documented offset, which decode to 1.75 mm as a 32-bit little-endian float. Reading eight bytes as a double consumed adjacent reserved bytes and produced the near-zero regression value.

Status: Implemented and covered by mocked decoder tests; broader real-dump validation remains useful.

## 2026-07-23: Bambu catalogue resolution is identifier-first

Decision: The saved-dump decoder resolves official Bambu filament names through a separate catalogue module seeded from validated local dump samples and known spool labels.

Reason: Marketed names such as Pumpkin Orange, Hot Pink, Desert Tan, Charcoal, and Terracotta cannot be safely inferred from generic RGB colour families. Stable tray material IDs, tray variant IDs, filament type, detailed filament type, and RGBA validation provide safer exact matching.

Status: Implemented for the current validated local dump dataset.

## 2026-07-23: RSA signature bytes are assembled but not verified

Decision: The saved-dump decoder exposes sectors 10 through 15 as an RSA signature region, excludes MIFARE sector trailers from signature payload bytes, and reports signature verification as not implemented.

Reason: Public Bambu RFID documentation identifies the region as an RSA-2048 signature generated with Bambu Lab's private key, but TL3D does not currently have or use a confirmed Bambu public key for verification. Preserving and assembling bytes is useful for comparison, but should not imply authenticity.

Status: Implemented as read-only metadata.
