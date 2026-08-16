#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description="Create ICO and ICNS files from the generated icon source.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ico", type=Path, required=True)
    parser.add_argument("--icns", type=Path, required=True)
    args = parser.parse_args()

    image = Image.open(args.input).convert("RGBA")
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (1024, 1024), (20, 39, 44, 255))
    offset = ((1024 - image.width) // 2, (1024 - image.height) // 2)
    canvas.alpha_composite(image, offset)
    args.ico.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(
        args.ico,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256), (512, 512)],
    )
    args.icns.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(
        args.icns,
        format="ICNS",
        sizes=[(16, 16), (32, 32), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )


if __name__ == "__main__":
    main()
