#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Write SHA-256 manifests for bundled release resources.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    files = sorted(path for path in args.root.rglob("*") if path.is_file() and path != args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the file directly consumable by `shasum -a 256 -c` without
    # warnings about non-checksum comment lines.
    lines: list[str] = []
    for path in files:
        lines.append(f"{digest(path)}  {path.relative_to(args.root).as_posix()}")
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
