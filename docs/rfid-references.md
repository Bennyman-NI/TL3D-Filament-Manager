# RFID References

## Bambu Lab RFID Tag Guide

- Upstream repository: `queengooborg/Bambu-Lab-RFID-Tag-Guide`
- URL: https://github.com/queengooborg/Bambu-Lab-RFID-Tag-Guide
- Licence observed: GPL-3.0, as reported by the GitHub repository licence metadata and root `LICENSE` file.

Files consulted:

- `LICENSE`: licence review.
- `deriveKeys.py`: documented Bambu UID-based key derivation using HKDF-SHA256, the documented 16-byte salt, and `RFID-A\0` / `RFID-B\0` contexts.
- `docs/ReadTags.md`: readout workflow reference, including deriving keys from UID and using those keys to dump MIFARE Classic tag data.
- `docs/BambuLabRfid.md`: block-layout reference for Bambu Lab tag memory.
- Repository `README.md`: high-level RFID tag behavior, including MIFARE tag use, UID-based key derivation, and signature constraints.

Implementation notes:

- TL3D independently implements the documented key derivation using Python standard-library `hmac` and `hashlib`.
- No upstream source file was copied into this repository.
- The standalone RFID identifier stores upstream attribution in saved JSON dumps.
- The tool uses only read-oriented PC/SC operations: reader-session key load, sector authentication, and block read.
- The saved-dump decoder independently implements documented field offsets and data types from `docs/BambuLabRfid.md`.
- Real-dump validation with a genuine Bambu PLA Basic Blue tag confirmed filament diameter at sector 1 block 1, offset 8 as a 4-byte little-endian IEEE-754 float. The upstream table marks the field as `float (LE)` but lists length `8`; TL3D treats the numeric representation as authoritative and reads 4 bytes so adjacent reserved bytes are not consumed.
- The upstream block overview identifies sectors 10 through 15 as the RSA-2048 signature region, while also documenting that every fourth block remains a MIFARE sector trailer unrelated to Bambu's memory format. TL3D excludes sector trailer blocks from assembled signature payload bytes.
- The upstream README describes the signature as generated with Bambu Lab's private key and checked by Bambu printers. TL3D preserves and assembles signature bytes for comparison only; it does not verify the signature or claim cryptographic validity.
- Unknown, reserved, uncertain, MIFARE trailer, and RSA signature region bytes are preserved as raw data rather than guessed.
- Exact Bambu catalogue-name resolution is seeded only from locally validated genuine saved dumps and known spool labels. Matching is identifier-first using tray material ID, tray variant ID, filament type, detailed filament type, and RGBA as validation; unknown identifiers remain unknown rather than being guessed from colour.
- Tag writing, cloning, emulation, UID changing, sector trailer modification, key changing, and brute-force key searching remain out of scope.

Licence implications:

- The upstream repository is GPL-3.0 licensed. Because this implementation is based on the published algorithm and documentation rather than copied code, TL3D records attribution and the upstream licence here. If future work copies upstream code or larger derived portions, review GPL-3.0 compatibility before distributing the result.

## piitaya/bambu-filaments

- Upstream repository: `piitaya/bambu-filaments`
- Runtime catalogue URL: https://raw.githubusercontent.com/piitaya/bambu-filaments/main/filaments.json
- Licence observed: MIT, as reported by the GitHub repository.

Implementation notes:

- TL3D uses this community-maintained catalogue as the primary updateable source for official Bambu filament names and colour names.
- The upstream project is keyed by the Bambu RFID variant ID and documents that the ID is stored on the RFID tag and maps to material plus colour.
- Official colour names ultimately derive from Bambu Studio data in the upstream project, with RFID dump/library data and SpoolmanDB cross-references used by that project.
- TL3D downloads and validates the JSON catalogue into `data/catalogues/bambu/filaments.json` with provenance metadata in `data/catalogues/bambu/metadata.json`.
- Machine-generated catalogue cache files are ignored by git through the existing `data/` ignore rule.
- The bundled TL3D validated catalogue remains as an offline fallback and is not merged over conflicting downloaded entries.
