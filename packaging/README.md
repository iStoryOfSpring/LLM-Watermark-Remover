# macOS 离线发行构建

当前发行目标为 Apple Silicon（arm64）和 macOS 13+。最终交付物是带有 Qwen3.5-2B、Python/PyTorch 运行时和原生 `WKWebView` 窗口的 `.app`，再封装为 DMG。

## 构建

在仓库根目录执行：

```bash
./scripts/build-macos.sh
```

脚本会：

1. 创建 `.venv-macos-arm64` 并安装 `requirements-macos-arm64.txt`；
2. 构建 `frontend/dist`；
3. 从 Python wheel metadata 和 `frontend/package-lock.json` 生成第三方许可证清单；
4. 生成 `.icns`、`.ico` 和资源 SHA-256 清单；
5. 使用 `packaging/local-rewrite.spec` 构建 onedir 后端；
6. 编译 `AppShell.swift`，组装 `.app`；
7. 生成并签名 DMG。

权重目录必须存在：

```text
model/Qwen3.5-2B/
```

构建不会联网下载模型。Qwen 权重和 `model/Qwen3.5-2B/LICENSE`、`README.md` 会整体进入发行包。

## 目录与进程关系

```text
LLM Watermark Remover.app/
└── Contents/
    ├── MacOS/LLMWatermarkRemover              Swift WKWebView 壳层
    └── Resources/
        ├── backend/LLMWatermarkRemoverBackend/ PyInstaller 后端和 Python runtime
        ├── model/Qwen3.5-2B/                  本地 Qwen 权重
        ├── frontend/dist/                     内置 UI
        └── LICENSES/                          第三方许可证与原文
```

Swift 壳层启动后端子进程，后端绑定 loopback 随机端口并通过 readiness 文件返回 URL。关闭窗口时终止子进程。用户任务写入 `~/Library/Application Support/LLM Watermark Remover`，不会写入应用包。

## 签名与 notarization

本机测试默认使用 ad-hoc 签名。公开发行需要 Developer ID Application 身份和 `xcrun notarytool` keychain profile：

```bash
CODESIGN_IDENTITY="Developer ID Application: ..." \
NOTARY_PROFILE="your-keychain-profile" \
./scripts/build-macos.sh
```

未配置签名身份的构建只能用于本机验证。
