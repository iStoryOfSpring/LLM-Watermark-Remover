#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

(cd "$ROOT_DIR/frontend" && npm run build)

rm -rf "$ROOT_DIR/dist"
mkdir -p "$ROOT_DIR/dist/server" "$ROOT_DIR/dist/.openai"
cp -R "$ROOT_DIR/frontend/dist"/. "$ROOT_DIR/dist"/
NODE_PATH="$ROOT_DIR/frontend/node_modules" "$ROOT_DIR/frontend/node_modules/.bin/esbuild" \
  "$ROOT_DIR/worker/index.ts" \
  --bundle --format=esm --platform=browser --target=es2022 \
  --outfile="$ROOT_DIR/dist/server/index.js"
cp "$ROOT_DIR/.openai/hosting.json" "$ROOT_DIR/dist/.openai/hosting.json"
