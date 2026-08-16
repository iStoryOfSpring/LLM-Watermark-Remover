#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_ROOT="${MACOS_BUILD_DIR:-$ROOT_DIR/build/macos}"
VENV_DIR="${MACOS_BUILD_VENV:-$ROOT_DIR/.venv-macos-arm64}"
PYTHON_BIN="${PYTHON_BIN:-}"
APP_NAME="LLM Watermark Remover"
APP_DIR="$BUILD_ROOT/$APP_NAME.app"
BACKEND_DIST="$BUILD_ROOT/backend-dist"
BACKEND_WORK="$BUILD_ROOT/backend-work"
DMG_SOURCE="$BUILD_ROOT/dmg-source"
RELEASE_DIR="$ROOT_DIR/release"
DMG_PATH="$RELEASE_DIR/LLMWatermarkRemover-macos-arm64.dmg"

if [ "$(uname -m)" != "arm64" ]; then
  echo "macOS Apple Silicon (arm64) is required for this release build." >&2
  exit 1
fi

if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "未找到可用的 Python 3。" >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$RELEASE_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
BUILD_PYTHON="$VENV_DIR/bin/python"
"$BUILD_PYTHON" -m pip install --upgrade pip
"$BUILD_PYTHON" -m pip install -r "$ROOT_DIR/packaging/requirements-macos-arm64.txt"
"$BUILD_PYTHON" -m pip install --no-deps -e "$ROOT_DIR"

(cd "$ROOT_DIR/frontend" && npm ci && npm run build)

"$BUILD_PYTHON" "$ROOT_DIR/scripts/generate-licenses.py"
"$BUILD_PYTHON" "$ROOT_DIR/scripts/build-icons.py" \
  --input "$ROOT_DIR/assets/LLMWatermarkRemover-icon-source.png" \
  --ico "$BUILD_ROOT/LLMWatermarkRemover.ico" \
  --icns "$BUILD_ROOT/LLMWatermarkRemover.icns"

export PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/pyinstaller-config"
mkdir -p "$PYINSTALLER_CONFIG_DIR"
"$BUILD_PYTHON" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "$BACKEND_DIST" \
  --workpath "$BACKEND_WORK" \
  "$ROOT_DIR/packaging/local-rewrite.spec"

mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources/backend"
cp -R "$BACKEND_DIST/LLMWatermarkRemoverBackend" "$APP_DIR/Contents/Resources/backend/"
if [ ! -d "$ROOT_DIR/model/Qwen3.5-2B" ]; then
  echo "未找到本地 Qwen3.5-2B 权重目录：$ROOT_DIR/model/Qwen3.5-2B" >&2
  exit 1
fi
mkdir -p "$APP_DIR/Contents/Resources/frontend" "$APP_DIR/Contents/Resources/model" "$APP_DIR/Contents/Resources/config"
cp -R "$ROOT_DIR/frontend/dist" "$APP_DIR/Contents/Resources/frontend/"
cp -R "$ROOT_DIR/model/Qwen3.5-2B" "$APP_DIR/Contents/Resources/model/"
cp "$ROOT_DIR/config/default.json" "$APP_DIR/Contents/Resources/config/"
cp "$BUILD_ROOT/LLMWatermarkRemover.icns" "$APP_DIR/Contents/Resources/LLMWatermarkRemover.icns"
cp "$BUILD_ROOT/LLMWatermarkRemover.ico" "$APP_DIR/Contents/Resources/LLMWatermarkRemover.ico"
cp "$ROOT_DIR/LICENSE" "$ROOT_DIR/NOTICE" "$APP_DIR/Contents/Resources/"
cp -R "$ROOT_DIR/LICENSES" "$APP_DIR/Contents/Resources/"
cp "$ROOT_DIR/packaging/macos/Info.plist" "$APP_DIR/Contents/Info.plist"

swiftc -O -framework Cocoa -framework WebKit \
  -module-cache-path "$BUILD_ROOT/swift-module-cache" \
  "$ROOT_DIR/packaging/macos/AppShell.swift" \
  -o "$APP_DIR/Contents/MacOS/LLMWatermarkRemover"
chmod +x "$APP_DIR/Contents/MacOS/LLMWatermarkRemover"

"$BUILD_PYTHON" "$ROOT_DIR/scripts/create-release-manifest.py" \
  --root "$APP_DIR/Contents/Resources" \
  --output "$APP_DIR/Contents/Resources/RELEASE-SHA256SUMS.txt"

CODESIGN_IDENTITY="${CODESIGN_IDENTITY:--}"
codesign --force --deep --options runtime --sign "$CODESIGN_IDENTITY" "$APP_DIR"

rm -rf "$DMG_SOURCE"
mkdir -p "$DMG_SOURCE"
cp -R "$APP_DIR" "$DMG_SOURCE/"
ln -s /Applications "$DMG_SOURCE/Applications"
rm -f "$DMG_PATH"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_SOURCE" -ov -format UDZO "$DMG_PATH" >/dev/null
codesign --force --sign "$CODESIGN_IDENTITY" "$DMG_PATH"

if [ -n "${NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$DMG_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG_PATH"
fi

shasum -a 256 "$DMG_PATH" > "$DMG_PATH.sha256"
echo "Built: $APP_DIR"
echo "Built: $DMG_PATH"
