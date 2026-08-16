import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var backend: Process?
    private var readyFile: URL?
    private var shuttingDown = false

    private let appTitle = "LLM Watermark Remover"

    private var applicationSupport: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(appTitle, isDirectory: true)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        installMenu()
        createWindow()
        startBackend()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        stopBackend()
        return .terminateNow
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopBackend()
    }

    func windowWillClose(_ notification: Notification) {
        stopBackend()
        if !shuttingDown {
            shuttingDown = true
            NSApp.terminate(nil)
        }
    }

    private func installMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu(title: appTitle)
        appMenu.addItem(withTitle: "关于 \(appTitle)", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "退出 \(appTitle)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)
        NSApp.mainMenu = mainMenu
    }

    @objc private func showAbout() {
        let alert = NSAlert()
        alert.messageText = appTitle
        alert.informativeText = "本地离线文档处理工具\n\n项目采用 Apache-2.0。第三方许可证可在应用内“开源许可证”链接查看。"
        alert.alertStyle = .informational
        alert.addButton(withTitle: "好")
        alert.runModal()
    }

    private func createWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.translatesAutoresizingMaskIntoConstraints = true
        webView.loadHTMLString("""
        <!doctype html><html><head><meta charset="utf-8"><style>
        body { margin: 0; display: grid; place-items: center; min-height: 100vh; background: #f2f6f4; color: #14272c; font: 15px -apple-system, BlinkMacSystemFont, sans-serif; }
        .loading { text-align: center; } .dot { color: #08766f; }
        </style></head><body><div class="loading"><div>正在启动本地运行时<span class="dot">…</span></div><small>模型只在本机加载，不会联网下载</small></div></body></html>
        """, baseURL: nil)

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1260, height: 860),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = appTitle
        window.minSize = NSSize(width: 920, height: 620)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
    }

    private func startBackend() {
        do {
            let fileManager = FileManager.default
            try fileManager.createDirectory(at: applicationSupport, withIntermediateDirectories: true)
            let runDirectory = applicationSupport.appendingPathComponent("run", isDirectory: true)
            let logDirectory = applicationSupport.appendingPathComponent("logs", isDirectory: true)
            try fileManager.createDirectory(at: runDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: logDirectory, withIntermediateDirectories: true)
            if let staleFiles = try? fileManager.contentsOfDirectory(
                at: runDirectory,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
            ) {
                for staleFile in staleFiles where staleFile.lastPathComponent.hasPrefix("backend-") {
                    try? fileManager.removeItem(at: staleFile)
                }
            }

            let pid = ProcessInfo.processInfo.processIdentifier
            let ready = runDirectory.appendingPathComponent("backend-\(pid).json")
            readyFile = ready
            try? fileManager.removeItem(at: ready)

            guard let resourceURL = Bundle.main.resourceURL else {
                throw NSError(domain: "LLMWatermarkRemover", code: 1, userInfo: [NSLocalizedDescriptionKey: "应用资源目录不存在。"])
            }
            let backendURL = resourceURL
                .appendingPathComponent("backend", isDirectory: true)
                .appendingPathComponent("LLMWatermarkRemoverBackend", isDirectory: true)
                .appendingPathComponent("LLMWatermarkRemoverBackend")
            guard fileManager.isExecutableFile(atPath: backendURL.path) else {
                throw NSError(domain: "LLMWatermarkRemover", code: 2, userInfo: [NSLocalizedDescriptionKey: "应用内后端运行时不存在。"])
            }

            let logURL = logDirectory.appendingPathComponent("backend.log")
            if !fileManager.fileExists(atPath: logURL.path) {
                fileManager.createFile(atPath: logURL.path, contents: nil)
            }
            let logHandle = try FileHandle(forWritingTo: logURL)
            try logHandle.seekToEnd()

            let child = Process()
            child.executableURL = backendURL
            child.arguments = ["--no-browser", "--host", "127.0.0.1", "--port", "0", "--ready-file", ready.path]
            var environment = ProcessInfo.processInfo.environment
            environment["LOCAL_REWRITE_RESOURCE_ROOT"] = resourceURL.path
            environment["LOCAL_REWRITE_DATA_DIR"] = applicationSupport.path
            environment["HF_HUB_OFFLINE"] = "1"
            environment["TRANSFORMERS_OFFLINE"] = "1"
            environment["TOKENIZERS_PARALLELISM"] = "false"
            child.environment = environment
            child.currentDirectoryURL = resourceURL
            child.standardOutput = logHandle
            child.standardError = logHandle
            child.terminationHandler = { [weak self] process in
                try? logHandle.close()
                DispatchQueue.main.async {
                    guard let self, !self.shuttingDown else { return }
                    self.showError("本地后端已退出（状态码 \(process.terminationStatus)）。\n日志：\(logURL.path)")
                }
            }
            backend = child
            try child.run()
            waitForBackend(at: ready)
        } catch {
            showError(error.localizedDescription)
        }
    }

    private func waitForBackend(at file: URL, attempt: Int = 0) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            if let data = try? Data(contentsOf: file),
               let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let urlString = payload["url"] as? String,
               let url = URL(string: urlString) {
                DispatchQueue.main.async {
                    self.webView.load(URLRequest(url: url))
                }
                return
            }
            if attempt >= 240 || self.backend?.isRunning == false {
                DispatchQueue.main.async {
                    self.showError("本地运行时启动超时。请查看 Application Support/LLM Watermark Remover/logs/backend.log。")
                }
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                self.waitForBackend(at: file, attempt: attempt + 1)
            }
        }
    }

    private func stopBackend() {
        shuttingDown = true
        if let readyFile {
            try? FileManager.default.removeItem(at: readyFile)
        }
        if let backend, backend.isRunning {
            backend.terminate()
            backend.waitUntilExit()
        }
        self.backend = nil
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "LLM Watermark Remover 无法启动"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.addButton(withTitle: "退出")
        alert.runModal()
        stopBackend()
        NSApp.terminate(nil)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = navigationAction.request.url else { return nil }
        if isLocal(url) {
            webView.load(URLRequest(url: url))
        } else {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if isLocal(url) || url.scheme == "about" {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    private func isLocal(_ url: URL) -> Bool {
        guard let host = url.host else { return false }
        return (host == "127.0.0.1" || host == "localhost") && url.scheme == "http"
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
