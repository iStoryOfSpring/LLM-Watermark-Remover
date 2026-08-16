<div align="center">

# 🧽 LLM Watermark Remover

**Offline-first, document-faithful constrained rewriting workstation**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![macOS](https://img.shields.io/badge/macOS-13%2B%20Apple%20Silicon-black?logo=apple&logoColor=white)](https://support.apple.com/en-us/116943)
[![Model](https://img.shields.io/badge/Model-Qwen3.5--2B-0f766e)](https://huggingface.co/Qwen/Qwen3.5-2B)
[![License](https://img.shields.io/badge/License-Apache--2.0-green)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](https://github.com/iStoryOfSpring/LLM-Watermark-Remover/pulls)

English | [简体中文](#简体中文)

</div>

> A local document rewriting workstation for constrained, reviewable text changes. The macOS release embeds Qwen3.5-2B, performs inference locally, protects sensitive spans, validates every candidate, and never downloads a model at runtime.

## 📋 Table of Contents

- [✨ Key Improvements](#-key-improvements)
- [🛠️ Quick Start](#-quick-start)
- [📦 Release Download](#-release-download)
- [📁 Project Structure](#-project-structure)
- [🔧 Configuration](#-configuration)
- [🏗️ Development and Build](#-development-and-build)
- [📜 License](#-license)
- [🙏 Acknowledgments](#-acknowledgments)
- [📝 Changelog](#-changelog)

---

## ✨ Key Improvements

### 1. Fully local Apple Silicon desktop application

- Native AppKit + `WKWebView` window instead of a browser tab.
- Local FastAPI backend bound to `127.0.0.1` with automatic port selection and readiness checks.
- PyInstaller onedir backend with bundled Python, PyTorch, Transformers, frontend assets, model files, and license notices.
- No user-installed Python, Node.js, or runtime network access is required for the packaged application.

### 2. Document-faithful constrained rewriting

- Supports UTF-8 TXT and DOCX input, review, and export.
- Protects numbers, links, email addresses, code, entities, user dictionaries, and high-risk spans.
- Preserves DOCX structure with targeted OOXML patching instead of rebuilding paragraphs through `paragraph.text`.
- Keeps headings, tables, headers/footers, footnotes/endnotes, text boxes, equations, comments, table of contents, and citations protected by default.

### 3. Fail-closed validation pipeline

- Qwen only proposes `KEEP` or `REPLACE` candidates; it cannot write directly into a document.
- Numeric, entity, logic, semantic, and layout checks run before a candidate is accepted.
- An uncertain validation result keeps the original text and records the reason for review.
- The current repository does not ship an ONNX embedding model. Semantic checks use the deterministic n-gram fallback until an ONNX model is added and licensed.

### 4. Auditable offline data path

- Original files are never overwritten by the application.
- Jobs, exports, audit logs, SQLite data, and user dictionaries stay under the macOS Application Support directory.
- The model, frontend, defaults, and license notices inside the application bundle are read-only resources.
- The project code is Apache-2.0; every third-party component keeps its own license and attribution.

---

## 🛠️ Quick Start

### Requirements

- Apple Silicon Mac (`arm64`); Intel Macs are not supported by the first desktop release.
- macOS 13 or newer.
- 16 GB RAM recommended for the first Qwen3.5-2B load.
- At least 8 GB of free disk space for the downloaded package, installed application, and temporary mounting space.

The application is offline after the release files have been downloaded. The first document operation lazily loads Qwen3.5-2B and may take longer than later operations.

### Install from a release

The current package is published on the [GitHub Releases page](https://github.com/iStoryOfSpring/LLM-Watermark-Remover/releases). Because GitHub limits each release asset to less than 2 GiB, the DMG is published as four parts. Download all of these files into one directory:

```text
LLMWatermarkRemover-macos-arm64.dmg.part-aa
LLMWatermarkRemover-macos-arm64.dmg.part-ab
LLMWatermarkRemover-macos-arm64.dmg.part-ac
LLMWatermarkRemover-macos-arm64.dmg.part-ad
LLMWatermarkRemover-macos-arm64.parts.sha256
LLMWatermarkRemover-macos-arm64.dmg.sha256
```

Verify the parts, join the DMG, and verify the reconstructed file:

```bash
shasum -a 256 -c LLMWatermarkRemover-macos-arm64.parts.sha256

cat LLMWatermarkRemover-macos-arm64.dmg.part-aa \
    LLMWatermarkRemover-macos-arm64.dmg.part-ab \
    LLMWatermarkRemover-macos-arm64.dmg.part-ac \
    LLMWatermarkRemover-macos-arm64.dmg.part-ad \
    > LLMWatermarkRemover-macos-arm64.dmg

shasum -a 256 -c LLMWatermarkRemover-macos-arm64.dmg.sha256
```

Open the verified DMG, drag `LLM Watermark Remover.app` into `Applications`, and launch it. If macOS shows a security warning for an unsigned local build, use Finder's **Open** action once or publish a notarized Developer ID build.

### Use the workstation

1. Open a UTF-8 TXT or DOCX file.
2. Run the local rewrite pipeline.
3. Review each proposed change in the application window.
4. Accept, restore, or reject individual changes.
5. Export a new document copy using the native save dialog.

The application does not promise any third-party detector result. It provides constrained, inspectable text processing and keeps the original document intact.

---

## 📦 Release Download

### Why the DMG is split

The full Qwen3.5-2B checkpoint is about 4.3 GB and the complete DMG is about 3.6 GiB. GitHub Releases allows a release to contain many assets, but each individual asset must be smaller than 2 GiB. The build therefore creates four shorter binary parts instead of uploading one oversized DMG. See the [official GitHub release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

Do not upload the unsplit `LLMWatermarkRemover-macos-arm64.dmg` to GitHub Releases. Upload the four `.part-*` files and both checksum files. The parts are not separate applications; they must be concatenated in alphabetical order before opening the DMG.

### Publish the generated assets

After building on an Apple Silicon Mac, upload these files from `release/` to the release page:

```text
LLMWatermarkRemover-macos-arm64.dmg.part-aa
LLMWatermarkRemover-macos-arm64.dmg.part-ab
LLMWatermarkRemover-macos-arm64.dmg.part-ac
LLMWatermarkRemover-macos-arm64.dmg.part-ad
LLMWatermarkRemover-macos-arm64.parts.sha256
LLMWatermarkRemover-macos-arm64.dmg.sha256
```

The original DMG is intentionally retained locally for verification but should not be selected in the GitHub upload box.

---

## 📁 Project Structure

```text
LLM-Watermark-Remover/
├── backend/                         # FastAPI API, CLI, MCP, document pipeline
│   ├── app/                         # Runtime modules
│   └── tests/                       # Backend tests and fixtures
├── config/                          # Default runtime configuration
├── frontend/                        # React + Vite user interface
├── model/Qwen3.5-2B/                # Model card and license; weights stay local
├── packaging/                       # PyInstaller, Swift shell, Info.plist
├── scripts/                         # Build, license, icon, manifest, split scripts
├── LICENSE                          # Apache License 2.0 for project code
├── NOTICE                           # Project and distribution notices
├── LICENSES/                        # Third-party notice and original license texts
├── pyproject.toml                   # Python package metadata and dependencies
├── frontend/package-lock.json       # Locked frontend dependency tree
└── README.md                        # This file
```

The `build/`, `release/`, `node_modules/`, `.venv-macos-arm64/`, runtime data, and multi-GB model weights are generated or local-only files and are intentionally ignored by normal Git commits.

---

## 🔧 Configuration

### Packaged application data

The desktop application stores mutable data at:

```text
~/Library/Application Support/LLM Watermark Remover/
```

This includes jobs, exported working copies, the SQLite database, user dictionaries, logs, and backend readiness files. The application bundle remains read-only.

### Development overrides

The development server preserves these environment variables for testing and local development:

```bash
export LOCAL_REWRITE_MODEL_PATH="/path/to/Qwen3.5-2B"
export LOCAL_REWRITE_DATA_DIR="/path/to/local-data"
export LOCAL_REWRITE_ALLOW_SEMANTIC_FALLBACK=true
```

The packaged build uses `local_files_only=True` and never downloads the model at runtime.

---

## 🏗️ Development and Build

### Run locally

Development requires Python 3.11+, Node.js 18+, and npm:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,local-llm]"

cd frontend
npm ci
cd ..
./start.sh
```

The development services default to:

```text
API:  http://127.0.0.1:8000
UI:   http://127.0.0.1:5173
```

To start only the backend:

```bash
python -m backend.app.desktop --no-browser
```

### Build the macOS package

Run this on an Apple Silicon Mac with the local model directory present:

```bash
./scripts/build-macos.sh
```

The build script creates a fixed arm64 Python environment, builds the React frontend, regenerates third-party notices, creates the icons and release manifest, packages the PyInstaller backend, compiles the native shell, creates the DMG, and automatically generates the GitHub-compatible split assets.

Required local model directory:

```text
model/Qwen3.5-2B/
```

Build outputs:

```text
build/macos/LLM Watermark Remover.app
release/LLMWatermarkRemover-macos-arm64.dmg
release/LLMWatermarkRemover-macos-arm64.dmg.part-aa
release/LLMWatermarkRemover-macos-arm64.dmg.part-ab
release/LLMWatermarkRemover-macos-arm64.dmg.part-ac
release/LLMWatermarkRemover-macos-arm64.dmg.part-ad
release/LLMWatermarkRemover-macos-arm64.dmg.sha256
release/LLMWatermarkRemover-macos-arm64.parts.sha256
```

If a DMG already exists and only the release assets need to be regenerated:

```bash
./scripts/split-release-dmg.sh release/LLMWatermarkRemover-macos-arm64.dmg
```

The split size defaults to 1,000,000,000 bytes so every part stays safely below GitHub's 2 GiB per-file limit and large uploads are less likely to time out. Override it only with another value below 2,147,483,648:

```bash
RELEASE_DMG_PART_SIZE=1800000000 \
  ./scripts/split-release-dmg.sh release/LLMWatermarkRemover-macos-arm64.dmg
```

### Signing and notarization

Local test builds use ad-hoc signing. Public distribution should use a Developer ID Application identity and a configured `notarytool` keychain profile:

```bash
CODESIGN_IDENTITY="Developer ID Application: ..." \
NOTARY_PROFILE="your-keychain-profile" \
./scripts/build-macos.sh
```

Without a signing identity, the result is intended for local testing only.

### Tests

```bash
pytest -q
cd frontend && npm run build
python3 -m compileall -q backend scripts
```

Release validation should also confirm that the application launches without Python or Node.js installed, Qwen does not trigger a network download, TXT/DOCX import and export work, the backend exits when the window closes, and the reconstructed DMG checksum matches.

---

## 📜 License

The project code is released under the **Apache License 2.0**, copyright `Chen Siyu`. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Third-party software is not re-licensed as Apache-2.0. The distribution preserves the original licenses, copyright notices, and package metadata for all direct and transitive components, including:

- **Python and native runtime**: FastAPI, Uvicorn, Starlette, AnyIO, Pydantic, python-multipart, lxml, python-docx, jieba, NumPy, Pillow, safetensors, Transformers, tokenizers, Hugging Face Hub, PyTorch, PyInstaller, setuptools, packaging, and their transitive dependencies.
- **Frontend and build toolchain**: React, React DOM, React Refresh, Vite, TypeScript, Lucide React, fflate, Babel, esbuild, Rollup, PostCSS, Browserslist, and their transitive dependencies.
- **Model**: Qwen3.5-2B and the model card/license supplied by Qwen.

The complete generated package list is in [LICENSES/THIRD_PARTY_NOTICES.md](LICENSES/THIRD_PARTY_NOTICES.md). Original license and notice texts are in [LICENSES/texts/](LICENSES/texts/). Regenerate the list with:

```bash
python scripts/generate-licenses.py
```

The source artwork for the application icon was generated with ImageGen. The resulting files are stored under `assets/` and are part of this project's visual assets.

---

## 🙏 Acknowledgments

- **Qwen team** — for Qwen3.5-2B and its local Transformers model release.
- **Hugging Face** — for the Transformers, safetensors, tokenizers, and model distribution ecosystem.
- **FastAPI, Uvicorn, Pydantic, lxml, python-docx, jieba, NumPy, PyTorch, and PyInstaller** — for the local processing and packaging runtime.
- **React, Vite, TypeScript, Lucide React, fflate, esbuild, Rollup, and the frontend dependency authors** — for the desktop UI and build toolchain.
- **Apple AppKit and WebKit** — for the native macOS window and local webview shell.

Each project above retains its own license; see [LICENSES/THIRD_PARTY_NOTICES.md](LICENSES/THIRD_PARTY_NOTICES.md) for the full attribution record.

---

## 📝 Changelog

### 0.1.0 — macOS Apple Silicon offline desktop release

- Added native AppKit + `WKWebView` desktop shell.
- Embedded Qwen3.5-2B, Python, PyTorch, Transformers, frontend assets, and license resources into the application bundle.
- Added offline local data storage, readiness checks, health checks, port selection, and backend cleanup on window close.
- Added TXT/DOCX review and export workflow with protected spans and fail-closed validation.
- Added generated PNG, ICNS, and ICO application icons.
- Added Apache-2.0 project license, NOTICE, complete third-party notices, model license files, and release SHA-256 manifests.
- Added automatic DMG splitting for GitHub Releases, where each uploaded asset must remain below 2 GiB.

<br>
<hr>
<br>

<h1 id="简体中文">🧽 LLM Watermark Remover：离线本地文档改写工作站</h1>

> 面向 TXT/DOCX 的本地优先、文档保真、受约束改写工具。macOS 发行版内嵌 Qwen3.5-2B，在本机完成候选生成、敏感区域保护、逐条审阅、验证和导出，不需要安装 Python 或 Node.js，也不会在运行时联网下载模型。

## 📋 目录

- [✨ 核心提升](#-核心提升)
- [🛠️ 快速开始](#-快速开始)
- [📦 发行版下载](#-发行版下载)
- [📁 项目结构](#-项目结构)
- [🔧 配置](#-配置)
- [🏗️ 开发与构建](#-开发与构建)
- [📜 许可证](#-许可证)
- [🙏 致谢](#-致谢)
- [📝 变更记录](#-变更记录)

---

## ✨ 核心提升

### 1. Apple Silicon 原生离线桌面版

- 使用 AppKit + `WKWebView` 原生独立窗口，不依赖浏览器标签页。
- 本地 FastAPI 后端只监听 `127.0.0.1`，自动选择端口并通过 readiness 信息与壳层握手。
- PyInstaller onedir 包含 Python、PyTorch、Transformers、前端静态文件、Qwen 模型和许可证资源。
- 发行版不要求用户安装 Python、Node.js，也不会在运行时联网下载模型。

### 2. 文档保真的受约束改写

- 支持 UTF-8 TXT 和 DOCX 的导入、审阅与导出。
- 默认保护数字、链接、邮箱、代码、实体、用户词典和高风险区域。
- DOCX 使用定点 OOXML patch，不通过 `paragraph.text` 重建段落，尽量保持原始结构。
- 标题、表格、页眉页脚、脚注尾注、文本框、公式、批注、目录和引用默认保护。

### 3. Fail Closed 验证流水线

- Qwen 只提出 `KEEP` 或 `REPLACE` 候选，不能直接写入文档。
- 候选写入前经过数字、实体、逻辑、语义和版式检查。
- 任一验证不确定时保留原文，并记录失败原因供审阅。
- 当前仓库没有随包提供 ONNX embedding 模型，语义门使用 deterministic n-gram fallback。

### 4. 可审计的本地数据路径

- 原文件不会被应用覆盖。
- 任务、导出副本、审计日志、SQLite 数据和用户词典写入 macOS Application Support。
- 应用包内的模型、前端、默认配置和许可证是只读资源。
- 项目代码采用 Apache-2.0；第三方库继续保留各自的许可证、版权和 NOTICE。

---

## 🛠️ 快速开始

### 环境要求

- Apple Silicon Mac（`arm64`）；首版不支持 Intel Mac。
- macOS 13 或更高版本。
- 建议 16 GB 或以上内存，以获得更顺畅的首次 Qwen3.5-2B 加载体验。
- 建议至少预留 8 GB 可用磁盘空间，用于下载分卷、合并 DMG、安装应用和临时挂载。

下载发行文件后，应用运行不需要网络。第一次处理文档时会懒加载 Qwen3.5-2B，首次加载可能明显慢于后续操作。

### 下载与安装发行版

前往 [GitHub Releases](https://github.com/iStoryOfSpring/LLM-Watermark-Remover/releases)，将以下 5 个文件全部下载到同一目录：

```text
LLMWatermarkRemover-macos-arm64.dmg.part-aa
LLMWatermarkRemover-macos-arm64.dmg.part-ab
LLMWatermarkRemover-macos-arm64.dmg.part-ac
LLMWatermarkRemover-macos-arm64.dmg.part-ad
LLMWatermarkRemover-macos-arm64.parts.sha256
LLMWatermarkRemover-macos-arm64.dmg.sha256
```

GitHub 单个 Release 附件不能超过 2 GiB，而完整 DMG 约 3.6 GiB，所以 DMG 被拆成四个更短的分卷。先验证分卷，再合并和验证完整 DMG：

```bash
shasum -a 256 -c LLMWatermarkRemover-macos-arm64.parts.sha256

cat LLMWatermarkRemover-macos-arm64.dmg.part-aa \
    LLMWatermarkRemover-macos-arm64.dmg.part-ab \
    LLMWatermarkRemover-macos-arm64.dmg.part-ac \
    LLMWatermarkRemover-macos-arm64.dmg.part-ad \
    > LLMWatermarkRemover-macos-arm64.dmg

shasum -a 256 -c LLMWatermarkRemover-macos-arm64.dmg.sha256
```

双击已验证的 DMG，将 `LLM Watermark Remover.app` 拖入 `Applications`，然后启动应用。未配置 Developer ID 的本机测试包第一次打开时，可能需要在 Finder 中右键选择“打开”。

### 使用工作站

1. 打开 UTF-8 TXT 或 DOCX 文件。
2. 运行本地改写流水线。
3. 在应用窗口中逐条审阅候选改动。
4. 接受、恢复或拒绝单条改动。
5. 通过原生保存对话框导出新的文件副本。

本工具不承诺任何第三方检测结果，只提供受约束、可复核的文本处理；原文件不会被覆盖。

---

## 📦 发行版下载

### 为什么要拆分 DMG

完整 Qwen3.5-2B 权重约 4.3 GB，最终 DMG 约 3.6 GiB。GitHub Releases 允许一个 Release 包含多个附件，但每个附件必须小于 2 GiB。因此构建脚本会自动生成四个更短的分卷，而不是上传一个超大 DMG。详见 [GitHub 官方 Release 限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。

不要把未拆分的 `LLMWatermarkRemover-macos-arm64.dmg` 上传到 GitHub Release。应上传四个 `.part-*` 文件和两个校验文件。分卷不是四个独立应用，必须按字母顺序合并后才能打开。

### 发布时上传的文件

构建完成后，在 GitHub Release 页面上传 `release/` 中的：

```text
LLMWatermarkRemover-macos-arm64.dmg.part-aa
LLMWatermarkRemover-macos-arm64.dmg.part-ab
LLMWatermarkRemover-macos-arm64.dmg.part-ac
LLMWatermarkRemover-macos-arm64.dmg.part-ad
LLMWatermarkRemover-macos-arm64.parts.sha256
LLMWatermarkRemover-macos-arm64.dmg.sha256
```

原始 DMG 会保留在本地用于校验，但不要在 GitHub 上传框中选择它。

---

## 📁 项目结构

```text
LLM-Watermark-Remover/
├── backend/                         # FastAPI、CLI、MCP、文档处理流水线
│   ├── app/                         # 后端运行模块
│   └── tests/                       # 后端测试与 fixture
├── config/                          # 默认运行配置
├── frontend/                        # React + Vite 用户界面
├── model/Qwen3.5-2B/                # 模型卡和许可证；权重保留在本地
├── packaging/                       # PyInstaller、Swift 壳层、Info.plist
├── scripts/                         # 构建、许可证、图标、清单、分卷脚本
├── LICENSE                          # 项目代码 Apache-2.0 许可证
├── NOTICE                           # 项目与发行 NOTICE
├── LICENSES/                        # 第三方归属和许可证原文
├── pyproject.toml                   # Python 包元数据和依赖
├── frontend/package-lock.json       # 锁定的前端依赖树
└── README.md                        # 本文件
```

`build/`、`release/`、`node_modules/`、`.venv-macos-arm64/`、运行数据和数 GB 的模型权重是生成文件或本地文件，默认不会进入普通 Git 提交。

---

## 🔧 配置

### 发行版数据目录

桌面版将可变数据写入：

```text
~/Library/Application Support/LLM Watermark Remover/
```

其中包括任务、导出工作副本、SQLite 数据库、用户词典、日志和后端 readiness 文件；应用包本身保持只读。

### 开发环境变量

开发和测试仍支持以下变量：

```bash
export LOCAL_REWRITE_MODEL_PATH="/path/to/Qwen3.5-2B"
export LOCAL_REWRITE_DATA_DIR="/path/to/local-data"
export LOCAL_REWRITE_ALLOW_SEMANTIC_FALLBACK=true
```

发行版使用 `local_files_only=True`，运行时禁止模型下载。

---

## 🏗️ 开发与构建

### 本地运行

开发环境需要 Python 3.11+、Node.js 18+ 和 npm：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,local-llm]"

cd frontend
npm ci
cd ..
./start.sh
```

开发模式默认启动：

```text
API： http://127.0.0.1:8000
UI：  http://127.0.0.1:5173
```

也可以只启动后端：

```bash
python -m backend.app.desktop --no-browser
```

### 构建 macOS 发行版

必须在 Apple Silicon Mac 上执行，并准备完整模型目录：

```bash
./scripts/build-macos.sh
```

脚本会创建固定的 arm64 Python 构建环境，构建 React 前端，生成第三方许可证清单、图标和应用资源 SHA-256 清单，打包 PyInstaller 后端，编译 Swift 壳层，生成 DMG，并自动生成适合 GitHub Release 的分卷和校验文件。

模型目录必须存在：

```text
model/Qwen3.5-2B/
```

构建输出：

```text
build/macos/LLM Watermark Remover.app
release/LLMWatermarkRemover-macos-arm64.dmg
release/LLMWatermarkRemover-macos-arm64.dmg.part-aa
release/LLMWatermarkRemover-macos-arm64.dmg.part-ab
release/LLMWatermarkRemover-macos-arm64.dmg.part-ac
release/LLMWatermarkRemover-macos-arm64.dmg.part-ad
release/LLMWatermarkRemover-macos-arm64.dmg.sha256
release/LLMWatermarkRemover-macos-arm64.parts.sha256
```

如果 DMG 已经存在，只需要重新生成发行分卷：

```bash
./scripts/split-release-dmg.sh release/LLMWatermarkRemover-macos-arm64.dmg
```

分卷大小默认为 1,000,000,000 字节，确保每个文件安全低于 GitHub 的 2 GiB 限制，也降低长时间上传中断的概率。如需调整，必须保持小于 2,147,483,648：

```bash
RELEASE_DMG_PART_SIZE=1800000000 \
  ./scripts/split-release-dmg.sh release/LLMWatermarkRemover-macos-arm64.dmg
```

### 签名与 notarization

本机测试默认使用 ad-hoc 签名。公开发行需要 Developer ID Application 身份和 `notarytool` keychain profile：

```bash
CODESIGN_IDENTITY="Developer ID Application: ..." \
NOTARY_PROFILE="your-keychain-profile" \
./scripts/build-macos.sh
```

未配置签名身份的构建只能用于本机测试。

### 测试

```bash
pytest -q
cd frontend && npm run build
python3 -m compileall -q backend scripts
```

发行验证还应检查：无 Python/Node.js 的机器可以启动、断网时 Qwen 不触发下载、TXT/DOCX 可以导入和导出、窗口关闭后后端进程退出、分卷合并后的 DMG 校验值正确。

---

## 📜 许可证

本项目代码采用 **Apache License 2.0**，版权归 `Chen Siyu` 所有。完整文本见 [LICENSE](LICENSE)，发行说明见 [NOTICE](NOTICE)。

第三方软件不会因为本项目采用 Apache-2.0 而被重新授权。发行包保留所有直接和传递依赖的原始许可证、版权声明和包元数据，包括：

- **Python 与原生运行时**：FastAPI、Uvicorn、Starlette、AnyIO、Pydantic、python-multipart、lxml、python-docx、jieba、NumPy、Pillow、safetensors、Transformers、tokenizers、Hugging Face Hub、PyTorch、PyInstaller、setuptools、packaging 及其传递依赖。
- **前端与构建工具链**：React、React DOM、React Refresh、Vite、TypeScript、Lucide React、fflate、Babel、esbuild、Rollup、PostCSS、Browserslist 及其传递依赖。
- **模型**：Qwen3.5-2B 及 Qwen 随模型提供的模型卡和许可证。

完整的逐项清单见 [LICENSES/THIRD_PARTY_NOTICES.md](LICENSES/THIRD_PARTY_NOTICES.md)，许可证原文见 [LICENSES/texts/](LICENSES/texts/)。如需重新收集：

```bash
python scripts/generate-licenses.py
```

应用图标源图由 ImageGen 生成，最终 PNG、ICNS 和 ICO 文件位于 `assets/`，属于本项目的视觉资源。

---

## 🙏 致谢

- **Qwen 团队**：提供 Qwen3.5-2B 及其 Transformers 模型发行内容。
- **Hugging Face**：提供 Transformers、safetensors、tokenizers 和模型分发生态。
- **FastAPI、Uvicorn、Pydantic、lxml、python-docx、jieba、NumPy、PyTorch、PyInstaller**：提供本地处理和打包运行时。
- **React、Vite、TypeScript、Lucide React、fflate、esbuild、Rollup 及前端依赖作者**：提供桌面 UI 和构建工具链。
- **Apple AppKit 与 WebKit**：提供原生 macOS 窗口和本地 WebView 壳层。

以上项目均继续保留各自许可证，完整归属记录见 [LICENSES/THIRD_PARTY_NOTICES.md](LICENSES/THIRD_PARTY_NOTICES.md)。

---

## 📝 变更记录

### 0.1.0 — macOS Apple Silicon 离线桌面版

- 新增 AppKit + `WKWebView` 原生桌面壳层。
- 将 Qwen3.5-2B、Python、PyTorch、Transformers、前端资源和许可证资源嵌入应用包。
- 新增本地数据目录、readiness/health 检查、自动端口选择和窗口关闭时的后端清理。
- 新增 TXT/DOCX 审阅与导出流程、保护区域和 Fail Closed 验证。
- 新增 PNG、ICNS、ICO 软件图标。
- 新增 Apache-2.0、NOTICE、完整第三方归属、模型许可证和发行 SHA-256 清单。
- 新增自动 DMG 分卷，解决 GitHub Releases 单附件不能超过 2 GiB 的限制；默认拆为四个更短分卷。

项目主页：[github.com/iStoryOfSpring/LLM-Watermark-Remover](https://github.com/iStoryOfSpring/LLM-Watermark-Remover)
