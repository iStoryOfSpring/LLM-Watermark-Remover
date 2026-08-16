# LLM Watermark Remover

一个本地优先、文档保真、可审计的中文局部改写工具。macOS 发行版内嵌 Qwen3.5-2B，本地完成候选生成、保护、验证和导出，不需要安装 Python、Node.js，也不会在运行时联网下载模型。
主要用于应对某些大厂宣称要对自己的AI添加水印。我的观点是，文字属于作者，不属于生成它的模型。


> 本工具不承诺任何第三方检测结果，只提供受约束、可复核的文本处理。原文件不会被覆盖，所有改动都可以逐条接受、恢复和导出。

## macOS 下载与使用

当前发行目标为 Apple Silicon Mac（arm64），支持 macOS 13 或更高版本。

1. 下载 `LLMWatermarkRemover-macos-arm64.dmg`。
2. 双击 DMG，将 `LLM Watermark Remover.app` 拖入 `Applications`。
3. 双击应用。窗口启动后会连接到应用内的本地 API。
4. 第一次处理文本时加载 Qwen3.5-2B，首次加载可能需要较长时间和较多内存。
5. 选择 TXT/DOCX，审阅变更，最后导出新的文件副本。

完整模型约 4.3 GB，发行包还包含 Python、PyTorch 和 Transformers 运行时。建议预留至少 8 GB 可用磁盘空间，并使用 16 GB 或以上内存的 Apple Silicon Mac。

## 功能与边界

- 支持 UTF-8 TXT 和 DOCX 正文普通段落。
- 默认执行词/短语级替换；有限句子改写需要显式开启。
- 保护数字、链接、邮箱、代码、实体、用户词典和高风险区域。
- DOCX 标题、表格、页眉页脚、脚注尾注、文本框、公式、批注、目录和引用默认保护。
- 使用原始 OOXML package 的定点 patch，不通过 `paragraph.text` 重写段落。
- 模型只提出 KEEP/REPLACE 候选，不能直接写入文档。
- 数字、实体、逻辑、语义或版式验证不确定时 Fail Closed，保留原文并记录原因。
- Qwen 负责本地候选生成；当前仓库没有随包提供 ONNX embedding 模型，语义门使用 deterministic n-gram fallback。

## 隐私与本地数据

发行版只监听 `127.0.0.1`。文档、任务结果、审计记录、SQLite 数据库和用户词典不会上传到云端。

用户数据存放在：

```text
~/Library/Application Support/LLM Watermark Remover/
```

应用包内的模型、前端、默认配置和许可证是只读资源。删除历史任务只删除本地任务副本，不会删除用户选择的原始文件。

## 开发运行

需要 Python 3.11+、Node.js 18+ 和 npm：

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

- API：`http://127.0.0.1:8000`
- Vite UI：`http://127.0.0.1:5173`

也可以直接运行后端：

```bash
python -m backend.app.desktop --no-browser
```

开发环境可通过以下变量覆盖模型和数据目录：

```bash
export LOCAL_REWRITE_MODEL_PATH="/path/to/Qwen3.5-2B"
export LOCAL_REWRITE_DATA_DIR="/path/to/local-data"
export LOCAL_REWRITE_ALLOW_SEMANTIC_FALLBACK=true
```

## 构建 macOS DMG

发行构建必须在 Apple Silicon Mac 上执行。构建机会创建独立的 Python 构建环境、构建前端、收集许可证、生成图标、打包 PyInstaller 后端、编译 Swift/WKWebView 壳层并生成 DMG：

```bash
./scripts/build-macos.sh
```

输出文件：

```text
release/LLMWatermarkRemover-macos-arm64.dmg
release/LLMWatermarkRemover-macos-arm64.dmg.sha256
build/macos/LLM Watermark Remover.app
```

公开发布时设置 Developer ID 签名和 notarization 配置：

```bash
CODESIGN_IDENTITY="Developer ID Application: ..." \
NOTARY_PROFILE="your-keychain-profile" \
./scripts/build-macos.sh
```

没有签名身份时脚本只生成用于本机测试的 ad-hoc 签名包，不应直接作为公开发行版。

## 模型来源

发行版内嵌 Hugging Face Transformers 格式的 [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) 权重。模型卡和原始 Apache-2.0 许可证随包保留在 `model/Qwen3.5-2B/README.md` 和 `model/Qwen3.5-2B/LICENSE`。

由于权重约 4.3 GB，模型文件默认不纳入普通源代码提交；构建机必须在 `model/Qwen3.5-2B/` 准备完整模型目录。构建结果会在应用资源中生成 `RELEASE-SHA256SUMS.txt`。

## 许可证与第三方归属

本项目代码采用 Apache License 2.0，版权归 `Chen Siyu` 所有，完整文本见 [`LICENSE`](LICENSE) 和 [`NOTICE`](NOTICE)。

第三方依赖不能因为本项目采用 Apache-2.0 而被重新声明为 Apache-2.0。发行包必须保留每个组件自己的许可证、版权声明和 NOTICE：

- Python：FastAPI、Uvicorn、Pydantic、lxml、python-docx、jieba、NumPy、PyTorch、Transformers、safetensors、tokenizers、PyInstaller 等直接和传递依赖。
- 前端：React、React DOM、Vite、TypeScript、Lucide React、fflate、esbuild 及 `package-lock.json` 中实际使用的依赖。
- 模型：Qwen3.5-2B 及其上游许可证/模型说明。

完整清单见 [`LICENSES/THIRD_PARTY_NOTICES.md`](LICENSES/THIRD_PARTY_NOTICES.md)，许可证原文见 [`LICENSES/texts/`](LICENSES/texts/)。构建时可重新生成：

```bash
python scripts/generate-licenses.py
```

软件图标源图由 ImageGen 生成，最终 macOS 图标和 ICO 文件位于：

```text
assets/LLMWatermarkRemover-icon-source.png
assets/LLMWatermarkRemover.icns
assets/LLMWatermarkRemover.ico
```

## 测试

```bash
pytest
cd frontend && npm run build
```

打包验证还应确认：断网时应用可以启动、Qwen 不触发下载、窗口关闭后后端进程退出、任务写入 Application Support、DMG 内包含模型校验清单和所有许可证文件。

## 项目结构

```text
backend/                 FastAPI、CLI、MCP、文档处理流水线
backend/tests/           后端测试
config/                  默认运行配置
frontend/                React + Vite UI
model/Qwen3.5-2B/        本地 Qwen 权重、模型卡和许可证
packaging/               PyInstaller、Swift 壳层和发行配置
scripts/                 网站、许可证、图标和 macOS DMG 构建脚本
LICENSES/                第三方许可证与 NOTICE
worker/                  独立的 Worker/site 实现，不进入 macOS 桌面包
```

项目主页：[github.com/iStoryOfSpring/LLM-Watermark-Remover](https://github.com/iStoryOfSpring/LLM-Watermark-Remover)
