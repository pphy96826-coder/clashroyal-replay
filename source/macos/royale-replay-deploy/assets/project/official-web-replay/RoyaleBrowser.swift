import Cocoa
import WebKit
import CFNetwork
import Network

enum BrowserFailure: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

enum RoyaleAddress {
    static func allowed(_ url: URL) -> Bool {
        guard url.scheme == "https", let host = url.host?.lowercased(),
              url.user == nil, url.password == nil, url.port == nil || url.port == 443 else { return false }
        return host == "royaleapi.com" || host.hasSuffix(".royaleapi.com")
    }
    static func resolve(_ text: String) throws -> URL {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let tag = value.uppercased().replacingOccurrences(of: "#", with: "")
        if tag.range(of: "^[0289PYLQGRJCUV]{6,16}$", options: .regularExpression) != nil {
            return URL(string: "https://royaleapi.com/player/\(tag)/battles")!
        }
        guard let url = URL(string: value.hasPrefix("https://") ? value : "https://" + value), allowed(url) else {
            throw BrowserFailure.message("请输入 RoyaleAPI HTTPS 网址或玩家 Tag。")
        }
        return url
    }
    static func replay(_ url: URL?) -> Bool {
        guard let url = url, allowed(url), url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) == "replay",
              let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems else { return false }
        let tags = query.filter { $0.name == "tag" }
        return tags.count == 1 && tags[0].value?.range(of: "^[A-Z0-9]{6,32}$", options: .regularExpression) != nil
    }
}

@available(macOS 14.0, *)
enum ExistingProxy {
    // Read, don't mutate the system/Clash configuration. Pin this browser's
    // transport to that already configured proxy and forbid direct failover.
    static func configuration() throws -> ProxyConfiguration {
        guard let raw = CFNetworkCopySystemProxySettings()?.takeRetainedValue(),
              let settings = raw as? [String: Any] else { throw BrowserFailure.message("无法读取现有系统代理；未发起联网请求。") }
        var config: ProxyConfiguration
        if (settings["HTTPSEnable"] as? NSNumber)?.boolValue == true,
           let host = settings["HTTPSProxy"] as? String,
           let number = settings["HTTPSPort"] as? NSNumber,
           let port = NWEndpoint.Port(rawValue: number.uint16Value), number.intValue > 0, number.intValue <= 65535 {
            config = ProxyConfiguration(httpCONNECTProxy: .hostPort(host: NWEndpoint.Host(host), port: port))
        } else if (settings["SOCKSEnable"] as? NSNumber)?.boolValue == true,
                  let host = settings["SOCKSProxy"] as? String,
                  let number = settings["SOCKSPort"] as? NSNumber,
                  let port = NWEndpoint.Port(rawValue: number.uint16Value), number.intValue > 0, number.intValue <= 65535 {
            config = ProxyConfiguration(socksv5Proxy: .hostPort(host: NWEndpoint.Host(host), port: port))
        } else { throw BrowserFailure.message("未检测到既有 HTTPS/SOCKS 代理。为遵守你的要求，本浏览器不直连，也不自动更改代理。") }
        config.allowFailover = false
        config.matchDomains = [""]
        config.excludedDomains = []
        return config
    }
}

@available(macOS 14.0, *)
final class RoyaleBrowser: NSObject, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
    let window: NSWindow
    let web: WKWebView
    let address = NSTextField(string: "https://royaleapi.com")
    let status = NSTextField(labelWithString: "现有代理 · 独立登录状态 · 不读取 Edge 数据")
    let downloadPlay = NSButton(title: "↓ 下载 HTML 并播放", target: nil, action: nil)
    let downloadOnly = NSButton(title: "仅保存 HTML", target: nil, action: nil)
    let back = NSButton(title: "←", target: nil, action: nil)
    let forward = NSButton(title: "→", target: nil, action: nil)
    var authNotice = false
    var available = false
    var capturing = false
    var onCapture: ((String, String, Bool) -> Void)?
    var onLog: ((String) -> Void)?

    override init() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        web = WKWebView(frame: .zero, configuration: config)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1140, height: 800),
                          styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        super.init()
        window.title = "RoyaleAPI · 搜索对局与下载播放"; window.minSize = NSSize(width: 880, height: 610)
        window.isReleasedWhenClosed = false; window.delegate = self
        web.navigationDelegate = self; web.uiDelegate = self
        address.placeholderString = "RoyaleAPI 网址，或玩家 Tag（如 #2PLLPVURP）"
        address.setAccessibilityLabel("RoyaleAPI 网址或玩家 Tag"); address.target = self; address.action = #selector(go)
        back.target = self; back.action = #selector(goBack); forward.target = self; forward.action = #selector(goForward)
        let open = NSButton(title: "打开", target: self, action: #selector(go))
        let home = NSButton(title: "首页", target: self, action: #selector(goHome))
        let reload = NSButton(title: "刷新", target: self, action: #selector(refresh))
        let row = NSStackView(views: [back, forward, address, open, home, reload]); row.spacing = 8
        address.setContentHuggingPriority(.defaultLow, for: .horizontal)
        downloadPlay.target = self; downloadPlay.action = #selector(captureAndPlay)
        downloadOnly.target = self; downloadOnly.action = #selector(captureOnly)
        let external = NSButton(title: "系统浏览器（Google登录）", target: self, action: #selector(openSystemBrowser))
        let actions = NSStackView(views: [downloadPlay, downloadOnly, external, status]); actions.spacing = 12
        status.lineBreakMode = .byWordWrapping; status.maximumNumberOfLines = 2
        let note = NSTextField(wrappingLabelWithString: "Google 不允许内嵌浏览器登录。请在已登录的 Edge/Chrome 中打开回放，再点击“RoyaleAPI → 官服回放”桥接扩展。\n浏览器登录不会同步到本窗口。未安装扩展时仍可手动保存 HTML；本窗口仅使用现有代理，禁止直连回退。")
        note.font = .systemFont(ofSize: 11); note.textColor = .secondaryLabelColor
        let stack = NSStackView(views: [row, actions, web, note]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 10
        stack.translatesAutoresizingMaskIntoConstraints = false; window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 14),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -14),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 14),
            stack.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -12),
            row.widthAnchor.constraint(equalTo: stack.widthAnchor), actions.widthAnchor.constraint(equalTo: stack.widthAnchor),
            web.widthAnchor.constraint(equalTo: stack.widthAnchor), web.heightAnchor.constraint(greaterThanOrEqualToConstant: 350),
            note.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
        updateButtons()
    }

    func show() {
        window.center(); window.makeKeyAndOrderFront(nil)
        if web.url == nil { navigate(URL(string: "https://royaleapi.com")!) }
    }
    func setAvailable(_ value: Bool) { available = value; updateButtons() }
    func updateButtons() {
        let eligible = available && !capturing && !web.isLoading && RoyaleAddress.replay(web.url)
        downloadPlay.isEnabled = eligible; downloadOnly.isEnabled = eligible
        back.isEnabled = web.canGoBack; forward.isEnabled = web.canGoForward
    }
    func fail(_ message: String) { status.stringValue = message; onLog?("网页：" + message); updateButtons() }
    func navigate(_ url: URL) {
        do {
            guard RoyaleAddress.allowed(url) else { throw BrowserFailure.message("本窗口只打开 RoyaleAPI HTTPS 页面。") }
            web.configuration.websiteDataStore.proxyConfigurations = [try ExistingProxy.configuration()]
            authNotice = false; address.stringValue = url.absoluteString; status.stringValue = "通过现有代理加载网页…"
            web.load(URLRequest(url: url, cachePolicy: .useProtocolCachePolicy, timeoutInterval: 45))
        } catch { fail(error.localizedDescription) }
    }
    @objc func go() { do { navigate(try RoyaleAddress.resolve(address.stringValue)) } catch { fail(error.localizedDescription) } }
    @objc func goHome() { navigate(URL(string: "https://royaleapi.com")!) }
    @objc func goBack() { web.goBack() }
    @objc func goForward() { web.goForward() }
    @objc func openSystemBrowser() {
        do {
            _ = try ExistingProxy.configuration()
            let url = web.url.flatMap { RoyaleAddress.allowed($0) ? $0 : nil } ?? URL(string: "https://royaleapi.com")!
            // Standard browser navigation only. Do not read/export its cookies,
            // credentials, profile or account data; no automatic return claimed.
            NSWorkspace.shared.open(url)
            fail("已交给系统浏览器。登录不会同步到本窗口；请用回放桥接扩展，或保存 HTML 回控制台。")
        } catch { fail(error.localizedDescription) }
    }
    @objc func refresh() {
        do { web.configuration.websiteDataStore.proxyConfigurations = [try ExistingProxy.configuration()]; web.reload() }
        catch { fail(error.localizedDescription) }
    }
    @objc func captureAndPlay() { capture(play: true) }
    @objc func captureOnly() { capture(play: false) }
    func capture(play: Bool) {
        guard available, !capturing, !web.isLoading, RoyaleAddress.replay(web.url), let requested = web.url else {
            fail("请等待工具就绪、页面加载完成，并打开一场 /replay?tag=… 详情页。"); return
        }
        capturing = true; updateButtons(); status.stringValue = "正在读取本页已加载的回放 HTML…"
        // Export the actual rendered DOM. No new HTTP request, cookie export,
        // hidden-tab fetch, raw replay injection or CAPTCHA automation.
        let script = """
        (() => ({url: location.href, html: '<!DOCTYPE html>\\n' + document.documentElement.outerHTML,
                 markers: document.querySelectorAll('[data-t][data-s][data-c][data-x][data-y]').length}))()
        """
        web.evaluateJavaScript(script) { [weak self] value, error in
            guard let self = self else { return }
            self.capturing = false
            if let error = error { self.fail("读取网页失败：" + error.localizedDescription); return }
            guard let result = value as? [String: Any], let html = result["html"] as? String,
                  let current = result["url"] as? String, let actual = URL(string: current),
                  actual == requested, self.web.url == requested, (result["markers"] as? Int ?? 0) > 0,
                  html.utf8.count <= 25 * 1024 * 1024 else {
                self.fail("页面没有完整回放，或已发生跳转。请完成登录/验证后重新打开回放详情。"); return
            }
            self.status.stringValue = play ? "正在保存 HTML 并启动原生回放…" : "正在保存 HTML…"
            self.onCapture?(html, current, play); self.updateButtons()
        }
    }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        status.stringValue = "网页加载中；若出现登录或验证，请自行完成。"; updateButtons()
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url { address.stringValue = url.absoluteString }
        status.stringValue = RoyaleAddress.replay(webView.url) ? "回放详情已打开 · 可下载 HTML 并播放" : "搜索玩家并进入一场 Replay 详情页"
        updateButtons()
    }
    func navigationFailure(_ error: Error) {
        let e = error as NSError
        if e.code == NSURLErrorCancelled || (e.domain == "WebKitErrorDomain" && e.code == 102) {
            if !authNotice { status.stringValue = "跳转已取消，当前页面仍可浏览；登录请使用系统浏览器。" }
            updateButtons(); return
        }
        fail("网页加载失败（不是 HTML 下载失败）：" + error.localizedDescription)
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { navigationFailure(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { navigationFailure(error) }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { fail("网页进程已退出，请点击刷新。") }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.host?.lowercased() == "accounts.google.com" {
            authNotice = true
            fail("Google 不允许内嵌浏览器登录。请点“系统浏览器（Google登录）”；这不是 HTML 下载错误。")
            decisionHandler(.cancel); return
        }
        if url.scheme == "about" { decisionHandler(.allow); return }
        // HTTPS subframes can perform the site's ordinary verification. Main
        // navigation/popups cannot silently open arbitrary external schemes.
        if navigationAction.targetFrame?.isMainFrame != false && !RoyaleAddress.allowed(url) {
            fail("已阻止站外跳转；请留在 RoyaleAPI 回放页面。"); decisionHandler(.cancel); return
        }
        guard url.scheme == "https" else { decisionHandler(.cancel); return }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if navigationAction.request.url?.host?.lowercased() == "accounts.google.com" {
            authNotice = true; fail("Google 登录请使用系统浏览器；内置窗口不共享系统浏览器登录状态。")
            return nil
        }
        if let url = navigationAction.request.url, RoyaleAddress.allowed(url) { navigate(url) }
        return nil
    }
}
