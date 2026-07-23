from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from . import decoder
except ImportError:  # pragma: no cover - supports direct script execution
    import decoder


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decode a saved TL3D Bambu RFID raw dump JSON file.")
    parser.add_argument("dump_file", type=Path, help="Path to a saved raw RFID dump JSON file.")
    parser.add_argument("--json", action="store_true", help="Print structured decoded JSON instead of text.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    decoded = decoder.decode_file(args.dump_file)
    if args.json:
        print(json.dumps(decoded.to_dict(), indent=2))
    else:
        print(decoder.format_human_readable(decoded))
    return 1 if decoded.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
