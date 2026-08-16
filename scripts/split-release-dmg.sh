#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DMG_PATH="${1:-$ROOT_DIR/release/LLMWatermarkRemover-macos-arm64.dmg}"
PART_SIZE="${RELEASE_DMG_PART_SIZE:-1900000000}"

if [ ! -f "$DMG_PATH" ]; then
  echo "DMG not found: $DMG_PATH" >&2
  exit 1
fi

case "$PART_SIZE" in
  ''|*[!0-9]*)
    echo "RELEASE_DMG_PART_SIZE must be an integer." >&2
    exit 1
    ;;
esac

if [ "$PART_SIZE" -ge 2147483648 ]; then
  echo "RELEASE_DMG_PART_SIZE must be smaller than 2147483648 bytes." >&2
  exit 1
fi

DMG_DIR="$(cd "$(dirname "$DMG_PATH")" && pwd)"
DMG_NAME="$(basename "$DMG_PATH")"
PART_PREFIX="$DMG_DIR/$DMG_NAME.part-"
DMG_CHECKSUM="$DMG_PATH.sha256"
PART_MANIFEST="$DMG_DIR/${DMG_NAME%.dmg}.parts.sha256"

# The build owns these exact generated filenames. Remove stale two-letter parts
# so a later, smaller DMG cannot leave an obsolete extra part in release/.
rm -f "$PART_PREFIX"?? "$DMG_CHECKSUM" "$PART_MANIFEST"
split -b "$PART_SIZE" -a 2 "$DMG_PATH" "$PART_PREFIX"

(
  cd "$DMG_DIR"
  shasum -a 256 "$DMG_NAME" > "$(basename "$DMG_CHECKSUM")"
  shasum -a 256 "$DMG_NAME.part-"?? > "$(basename "$PART_MANIFEST")"
)

echo "Release assets:"
for part in "$PART_PREFIX"??; do
  part_size="$(wc -c < "$part" | tr -d ' ')"
  echo "  $part ($part_size bytes)"
done
echo "  $DMG_CHECKSUM"
echo "  $PART_MANIFEST"
