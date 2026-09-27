"""Regenerate or verify the checked-in core TerminusDB schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from c1.model.profiles import ProfileRegistry
from c1.storage.schema import generated_core_schema

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "profiles" / "core" / "terminus-schema.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated schema differs")
    args = parser.parse_args()
    content = (
        json.dumps(generated_core_schema(ProfileRegistry()), indent=2, ensure_ascii=False) + "\n"
    )
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != content:
            print(
                "Generated core schema differs from profiles/core/terminus-schema.json",
                file=sys.stderr,
            )
            return 1
        return 0
    TARGET.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
