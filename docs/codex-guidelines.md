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

## Completion Report

Every implementation task should conclude with a structured completion report. Adapt the shape for documentation-only or investigation-only tasks, but keep the same information explicit where it applies.

The report should contain:

1. Summary of changes
2. Files added
3. Files modified
4. Files deleted (if any)
5. Tests executed
6. Test results
7. Tests not run, with the reason
8. Manual testing still required
9. Known limitations or assumptions
10. Follow-up recommendations
11. Suggested Git commit message

For hardware-dependent work, call out:
- hardware assumptions
- verification completed
- verification still required by the user

Unless explicitly instructed:
- Do not commit changes.
- Do not push changes.
- Do not merge pull requests.


