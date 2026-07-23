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
- Unknown, reserved, uncertain, MIFARE trailer, and RSA signature bytes are preserved as raw data rather than guessed.
- Tag writing, cloning, emulation, UID changing, sector trailer modification, key changing, and brute-force key searching remain out of scope.

Licence implications:

- The upstream repository is GPL-3.0 licensed. Because this implementation is based on the published algorithm and documentation rather than copied code, TL3D records attribution and the upstream licence here. If future work copies upstream code or larger derived portions, review GPL-3.0 compatibility before distributing the result.
