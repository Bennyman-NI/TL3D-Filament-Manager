# Codex Guidelines

## Project workflow

- Read `README.md` and relevant `/docs` files before making changes.
- Keep `README.md` and affected documentation consistent with the implementation.
- Update `docs/roadmap.md` when a feature or milestone changes status.
- Record significant architectural or scope decisions in `docs/decision-log.md`.
- Prefer small, focused changes.
- Add or update tests where practical.
- Do not add dead code or speculative production code.

## RFID safety

- RFID functionality must remain read-only unless writing is explicitly authorised.
- Do not implement tag writing, cloning, emulation, or tag modification.
- Do not integrate proof-of-concept code into the main GUI without explicit approval.

## Reporting

Clearly report:

- files changed
- tests run
- limitations
- untested hardware assumptions
