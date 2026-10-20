import Cocoa
import UniformTypeIdentifiers

let sourceRoot = Bundle.main.object(forInfoDictionaryKey: "RoyaleProjectRoot") as? String ?? ""

final class ReplayConsole: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    let path = NSTextField(string: "")
    let status = NSTextField(labelWithString: "正在连接本地回放工具…")
    let match = NSTextField(labelWithString: "尚未载入对局")
    let log = NSTextView()
    let progress = NSProgressIndicator()
    let choose = NSButton(title: "选择 HTML…", target: nil, action: nil)
    let play = NSButton(title: "▶ 播放回放", target: nil, action: nil)
    let stop = NSButton(title: "■ 停止回放 / 取消准备", target: nil, action: nil)
    let speed = NSPopUpButton()
    let browse = NSButton(title: "RoyaleAPI 搜索 / 下载播放", target: nil, action: nil)
    let replaySaved = NSButton(title: "重放已保存回放", target: nil, action: nil)
    let removeSaved = NSButton(title: "移除已保存回放", target: nil, action: nil)
    var savedSHA: String?
    let addQueue = NSButton(title: "添加多个 HTML 到队列…", target: nil, action: nil)
    let nextQueue = NSButton(title: "播放下一个", target: nil, action: nil)
    let exportDiagnostic = NSButton(title: "导出诊断…", target: nil, action: nil)
    let queueInfo = NSTextField(labelWithString: "队列为空")
    var browserObject: AnyObject?
    var worker: Process?
    var input: FileHandle?
    var outputBuffer = Data()
    var busy = false
    var active = false
    var healthy = true
    var workerReady = false
    var duration: Double = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        appMenu.addItem(withTitle: "退出官服 HTML 回放", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let bridgeGuide = appMenu.addItem(withTitle: "浏览器扩展安装说明…", action: #selector(showBridgeGuide), keyEquivalent: "")
        bridgeGuide.target = self
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let editMenu = NSMenu(title: "编辑"); editItem.submenu = editMenu
        for (name, action, key) in [("拷贝", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: name, action: Selector(action), keyEquivalent: key)
        }
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 610),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "官服 HTML 回放控制台"; window.minSize = NSSize(width: 760, height: 530); window.delegate = self
        let container = NSView(); window.contentView = container
        let title = NSTextField(labelWithString: "官服 HTML 战斗回放")
        title.font = NSFont.systemFont(ofSize: 25, weight: .bold)
        let subtitle = NSTextField(labelWithString: "选择本地 HTML，或在内置 RoyaleAPI 浏览器找到对局并一键下载播放。")
        subtitle.textColor = .secondaryLabelColor
        path.placeholderString = "输入或粘贴 HTML 文件路径"; path.setAccessibilityLabel("HTML 文件路径")
        path.stringValue = UserDefaults.standard.string(forKey: "lastHTML") ?? ""
        choose.target = self; choose.action = #selector(pick)
        play.target = self; play.action = #selector(start); play.bezelStyle = .rounded; play.keyEquivalent = "\r"
        stop.target = self; stop.action = #selector(stopReplay)
        browse.target = self; browse.action = #selector(openRoyaleAPI)
        replaySaved.target = self; replaySaved.action = #selector(replaySelection)
        removeSaved.target = self; removeSaved.action = #selector(removeSelection)
        addQueue.target = self; addQueue.action = #selector(enqueueHTML)
        nextQueue.target = self; nextQueue.action = #selector(playNext)
        exportDiagnostic.target = self; exportDiagnostic.action = #selector(exportRecords)
        replaySaved.isEnabled = false; removeSaved.isEnabled = false
        play.isEnabled = false; stop.isEnabled = false
        speed.addItems(withTitles: ["0.25×", "0.5×", "1×", "2×", "4×"]); speed.selectItem(at: 2)
        speed.setAccessibilityLabel("播放倍速")
        let fileRow = NSStackView(views: [path, choose]); fileRow.orientation = .horizontal; fileRow.spacing = 10
        choose.setContentHuggingPriority(.required, for: .horizontal)
        let controls = NSStackView(views: [play, stop, NSTextField(labelWithString: "播放倍速"), speed, browse]); controls.spacing = 12
        let savedControls = NSStackView(views: [replaySaved, removeSaved, addQueue, nextQueue]); savedControls.spacing = 12
        let diagnosticControls = NSStackView(views: [exportDiagnostic]); diagnosticControls.spacing = 12
        progress.isIndeterminate = true; progress.style = .bar
        status.font = NSFont.systemFont(ofSize: 14, weight: .medium)
        status.lineBreakMode = .byWordWrapping; status.maximumNumberOfLines = 3
        match.textColor = .secondaryLabelColor; match.maximumNumberOfLines = 2
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.borderType = .noBorder
        log.isEditable = false; log.isSelectable = true
        log.backgroundColor = NSColor(calibratedRed: 0.06, green: 0.10, blue: 0.17, alpha: 1)
        log.textColor = NSColor(calibratedWhite: 0.9, alpha: 1)
        log.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        log.textContainerInset = NSSize(width: 10, height: 10)
        log.autoresizingMask = [.width]; log.isVerticallyResizable = true
        log.textContainer?.widthTracksTextView = true; scroll.documentView = log
        let note = NSTextField(wrappingLabelWithString: "不修改网络 · 不开启新模拟器 · 不覆盖其他对局 · 网页浏览仅使用现有代理\n按 HTML 加载塔楼部队与合法等级；缺省国王塔与同方塔楼等级一致。游戏内可暂停/继续。\n歧义技能搜索至多256个候选；终局塔血匹配仅代表推断匹配。录像与客户端平衡参数不同可能导致差异。")
        note.font = NSFont.systemFont(ofSize: 11); note.textColor = .secondaryLabelColor
        let stack = NSStackView(views: [title, subtitle, fileRow, controls, savedControls, diagnosticControls, queueInfo, status, progress, match, scroll, note])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 13
        stack.translatesAutoresizingMaskIntoConstraints = false; container.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: container.topAnchor, constant: 24),
            stack.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -20),
            fileRow.widthAnchor.constraint(equalTo: stack.widthAnchor),
            progress.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll.widthAnchor.constraint(equalTo: stack.widthAnchor), scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 180),
            status.widthAnchor.constraint(equalTo: stack.widthAnchor), note.widthAnchor.constraint(equalTo: stack.widthAnchor),
            match.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        append("控制台已打开。画面将在安卓1的游戏窗口显示，本窗口显示准备进度和日志。")
        startWorker()
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            guard let self = self, !self.workerReady, self.healthy else { return }
            self.status.stringValue = "本地工具尚未就绪：请检查 macOS 的“文稿/下载”文件访问提示并自行确认。"
            self.append("后台尚未读入项目脚本，没有提交回放。只需文件访问，不需要完全磁盘访问或网络改动。")
        }
    }

    func append(_ text: String) {
        let clock = DateFormatter(); clock.dateFormat = "HH:mm:ss"
        let line = "[\(clock.string(from: Date()))] \(text)\n"
        log.textStorage?.append(NSAttributedString(string: line, attributes: [.font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular), .foregroundColor: NSColor(calibratedWhite: 0.9, alpha: 1)]))
        log.scrollToEndOfDocument(nil)
    }

    func startWorker() {
        let process = Process(); process.executableURL = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "RoyalePython") as? String ?? "/usr/bin/python3")
        process.arguments = ["-u", sourceRoot + "/desktop_worker.py"]
        process.currentDirectoryURL = URL(fileURLWithPath: sourceRoot)
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        process.standardInput = stdin; process.standardOutput = stdout; process.standardError = stderr
        input = stdin.fileHandleForWriting
        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            DispatchQueue.main.async { self?.receive(data) }
        }
        stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if !data.isEmpty { DispatchQueue.main.async { self?.append(String(decoding: data, as: UTF8.self)) } }
        }
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.healthy = false; self.play.isEnabled = false; self.stop.isEnabled = false
                self.syncBrowser()
                self.status.stringValue = "回放工具已退出（\(process.terminationStatus)），请重新打开控制台。"
                self.append(self.status.stringValue)
            }
        }
        do { try process.run(); worker = process }
        catch { showError("无法启动本地工具：\(error.localizedDescription)") }
    }

    func receive(_ data: Data) {
        outputBuffer.append(data)
        while let newline = outputBuffer.firstIndex(of: 10) {
            let line = outputBuffer.prefix(upTo: newline); outputBuffer.removeSubrange(...newline)
            guard let event = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                  let kind = event["event"] as? String else { continue }
            let value = event["value"]
            switch kind {
            case "busy":
                busy = value as? Bool ?? false; play.isEnabled = !busy && healthy
                syncSaved()
                choose.isEnabled = !busy; path.isEditable = !busy; speed.isEnabled = !busy
                syncBrowser()
                if busy { progress.isIndeterminate = true; progress.startAnimation(nil) }
                else { progress.stopAnimation(nil) }
            case "ready":
                workerReady = true; play.isEnabled = true; stop.isEnabled = true
                syncBrowser()
                if let text = value as? String { status.stringValue = text; append(text) }
            case "status", "cancelled", "stopped", "recovered", "lobby-ready":
                if let text = value as? String { status.stringValue = text; append(text) }
                if kind == "stopped" || kind == "recovered" || kind == "lobby-ready" { active = false }
            case "saved":
                if let doc = value as? [String: Any] { savedSHA = doc["source_sha256"] as? String }
                else { savedSHA = nil }
                syncSaved()
            case "queue":
                if let rows = value as? [[String: Any]] {
                    let pending = rows.filter { ["queued", "parsing", "ready"].contains($0["state"] as? String ?? "") }
                    queueInfo.stringValue = "队列待播 \(pending.count) 场 · " + (pending.first?["name"] as? String ?? "暂无下一场")
                }
            case "log": if let text = value as? String { append(text) }
            case "run": if let text = value as? String { append("本轮日志：" + text) }
            case "match":
                if let doc = value as? [String: Any], let decks = doc["decks"] as? [[String: Any]] {
                    let names = decks.compactMap { ($0["source_player"] as? [String: Any])?["name"] as? String }
                    match.stringValue = names.joined(separator: "  vs  ") + "  ·  \(doc["retained_action_count"] ?? 0) 条指令  ·  原始时长 \(doc["source_duration_seconds"] ?? 0) 秒"
                }
            case "downloaded":
                if let doc = value as? [String: Any], let file = doc["path"] as? String {
                    path.stringValue = file; UserDefaults.standard.set(file, forKey: "lastHTML")
                    append("网页 HTML 已保存：" + file + " · \(doc["retained_action_count"] ?? 0) 条原始指令")
                }
            case "adopted": active = true; status.stringValue = "检测到本工具已有回放。可停止，或选择 HTML 重新播放。"; append(status.stringValue)
            case "playing", "resumed":
                active = true
                if let doc = value as? [String: Any] { duration = doc["duration"] as? Double ?? 0 }
                progress.stopAnimation(nil); progress.isIndeterminate = false; progress.maxValue = duration; progress.doubleValue = 0
                status.stringValue = kind == "resumed" ? "已连接原有回放，正在读取实际播放进度。" : "正在安卓1播放，请查看游戏窗口。"
                append(status.stringValue)
            case "position":
                if let doc = value as? [String: Any], let tick = doc["tick"] as? Int {
                    let seconds = Double(tick) / 20; progress.doubleValue = seconds
                    status.stringValue = String(format: "正在播放 · %.1f / %.1f 秒 · 原生引擎实际进度", seconds, duration)
                }
            case "complete":
                status.stringValue = "播放完毕 · 可重放已保存回放，或停止退出回放"; append(status.stringValue)
                window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
            case "error", "fatal": showError(value as? String ?? "未知错误")
            default: break
            }
        }
    }

    func send(_ command: [String: Any]) {
        guard healthy, let input = input, let data = try? JSONSerialization.data(withJSONObject: command) else { return }
        do { try input.write(contentsOf: data + Data([10])) }
        catch { showError("回放工具连接已关闭：\(error.localizedDescription)") }
    }

    func showError(_ text: String) {
        status.stringValue = "失败：" + text; append(status.stringValue)
        let alert = NSAlert(); alert.messageText = "回放未启动"; alert.informativeText = text
        alert.beginSheetModal(for: window)
    }

    @objc func exportRecords() {
        let warning = NSAlert(); warning.messageText = "导出本机诊断？"
        warning.informativeText = "只读导出最近任务的日志和执行记录，不含原始 HTML、游戏 APK 或浏览器 Cookie。含本机路径、进程信息和解析后的回放数据，请私下发送。不会停止、重试或清理游戏。"
        warning.addButton(withTitle: "选择保存位置"); warning.addButton(withTitle: "取消")
        guard warning.runModal() == .alertFirstButtonReturn else { return }
        let panel = NSSavePanel(); panel.allowedContentTypes = [.zip]
        panel.nameFieldStringValue = "回放诊断-\(Int(Date().timeIntervalSince1970)).zip"
        panel.beginSheetModal(for: window) { response in
            guard response == .OK, let url = panel.url else { return }
            self.exportDiagnostic.isEnabled = false
            let python = Bundle.main.object(forInfoDictionaryKey: "RoyalePython") as? String ?? "/usr/bin/python3"
            DispatchQueue.global(qos: .utility).async {
                let process = Process(); process.executableURL = URL(fileURLWithPath: python)
                process.arguments = [sourceRoot + "/diagnostic_export.py", "--store", sourceRoot + "/console-runs", "--output", url.path]
                let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
                var message: String
                do {
                    try process.run(); let data = pipe.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
                    message = process.terminationStatus == 0 ? "诊断 ZIP 已保存：\(url.path)\n请私下发送；游戏现场未改变。" : "导出未完成，请换一个新文件名重试。\n" + String(decoding: data.suffix(1800), as: UTF8.self)
                } catch { message = "导出未完成：\(error.localizedDescription)" }
                let result = message
                DispatchQueue.main.async {
                    self.exportDiagnostic.isEnabled = true; self.append(result)
                    let alert = NSAlert(); alert.messageText = "诊断导出"; alert.informativeText = result
                    alert.addButton(withTitle: "知道了"); alert.beginSheetModal(for: self.window)
                }
            }
        }
    }

    @objc func pick() {
        let dialog = NSOpenPanel(); dialog.allowedContentTypes = [.html]; dialog.canChooseDirectories = false
        dialog.title = "选择 RoyaleAPI 回放 HTML"
        dialog.beginSheetModal(for: window) { response in
            if response == .OK, let url = dialog.url { self.path.stringValue = url.path }
        }
    }

    @objc func start() {
        if busy || !workerReady { return }
        let html = path.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if html.isEmpty { pick(); return }
        let speeds = [0.25, 0.5, 1.0, 2.0, 4.0]
        UserDefaults.standard.set(html, forKey: "lastHTML")
        status.stringValue = "已收到播放请求，开始准备…"; append(status.stringValue)
        send(["command": "play", "html": html, "speed": speeds[speed.indexOfSelectedItem]])
    }

    func syncBrowser() {
        if #available(macOS 14.0, *) { (browserObject as? RoyaleBrowser)?.setAvailable(workerReady && healthy && !busy) }
    }

    func syncSaved() {
        replaySaved.isEnabled = savedSHA != nil && healthy && workerReady && !busy
        removeSaved.isEnabled = replaySaved.isEnabled
        nextQueue.isEnabled = healthy && workerReady && !busy
    }

    @objc func enqueueHTML() {
        let dialog = NSOpenPanel(); dialog.allowedContentTypes = [.html, .json]; dialog.allowsMultipleSelection = true
        dialog.canChooseDirectories = false; dialog.title = "添加 HTML 或诊断包；播放中仍可入队并后台解析"
        dialog.beginSheetModal(for: window) { response in
            if response == .OK { self.send(["command": "queue-add", "htmls": dialog.urls.map { $0.path }]) }
        }
    }

    @objc func playNext() {
        let speeds = [0.25, 0.5, 1.0, 2.0, 4.0]
        send(["command": "queue-next", "speed": speeds[speed.indexOfSelectedItem]])
    }

    @objc func replaySelection() {
        guard !busy, let hash = savedSHA else { return }
        let speeds = [0.25, 0.5, 1.0, 2.0, 4.0]
        send(["command": "replay-saved", "source_sha256": hash, "speed": speeds[speed.indexOfSelectedItem]])
    }

    @objc func removeSelection() {
        guard !busy, let hash = savedSHA else { return }
        let alert = NSAlert(); alert.messageText = "移除保存的回放选择？"
        alert.informativeText = "原始 HTML、缓存和诊断记录仍保留；不会中断正在播放的游戏。"
        alert.addButton(withTitle: "移除选择"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn { self.send(["command": "remove-saved", "source_sha256": hash]) }
        }
    }

    @objc func openRoyaleAPI() {
        guard #available(macOS 14.0, *) else { showError("内置浏览器需要 macOS14及以上，以支持既有代理且禁止直连回退。"); return }
        if browserObject == nil {
            let browser = RoyaleBrowser()
            browser.onLog = { [weak self] text in self?.append(text) }
            browser.onCapture = { [weak self] html, url, play in
                guard let self = self, !self.busy, self.workerReady else { return }
                let speeds = [0.25, 0.5, 1.0, 2.0, 4.0]
                self.send(["command": play ? "capture-play" : "capture-save", "html": html, "url": url,
                           "speed": speeds[self.speed.indexOfSelectedItem]])
            }
            browserObject = browser
        }
        syncBrowser(); (browserObject as? RoyaleBrowser)?.show()
    }

    @objc func showBridgeGuide() {
        let alert = NSAlert(); alert.messageText = "使用已登录的 Edge / Chrome 一键回传"
        alert.informativeText = "Google 不支持内嵌浏览器登录。请在你已登录的标准浏览器中打开 RoyaleAPI 回放详情，再点击“RoyaleAPI → 官服回放”扩展。\n\n本地扩展目录：\n" + sourceRoot + "/browser-extension\n\n扩展权限仅 activeTab、scripting、nativeMessaging；无 Cookie、代理或后台采集权限。需加载此本地扩展并注册本地桥接后才能使用。"
        alert.addButton(withTitle: "知道了"); alert.beginSheetModal(for: window)
    }

    @objc func stopReplay() {
        status.stringValue = busy ? "已请求取消，请等待当前原生步骤安全结束…" : "正在核对回放归属并停止…"
        append(status.stringValue); send(["command": "stop"])
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if busy {
            let alert = NSAlert(); alert.messageText = "当前步骤仍在进行"
            alert.informativeText = "请先取消并等待当前原生步骤安全结束，再退出控制台。"
            alert.addButton(withTitle: "取消准备，继续等待"); alert.addButton(withTitle: "保持运行")
            if alert.runModal() == .alertFirstButtonReturn { send(["command": "stop"]) }
            return .terminateCancel
        }
        if active {
            let alert = NSAlert(); alert.messageText = "关闭控制台不会停止安卓1中的回放"
            alert.informativeText = "如需停止，请先点“停止回放”。"
            alert.addButton(withTitle: "仅关闭控制台"); alert.addButton(withTitle: "返回")
            if alert.runModal() != .alertFirstButtonReturn { return .terminateCancel }
        }
        send(["command": "shutdown"]); try? input?.close()
        return .terminateNow
    }
}

@main
struct ReplayConsoleMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = ReplayConsole()
        app.setActivationPolicy(.regular); app.delegate = delegate
        app.run()
    }
}
