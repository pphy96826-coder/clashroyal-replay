import Foundation
import AppKit
import CryptoKit

enum BridgeError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

enum Bridge {
    static let origin = "chrome-extension://dbjcdkkejbaccfpnicafnkjaehkjhkjf/"
    static let app = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    static func queue() throws -> URL {
        let data = try Data(contentsOf: app.appendingPathComponent("Contents/Info.plist"))
        guard let info = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              let id = info["RoyaleDeploymentID"] as? String,
              id.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { throw BridgeError.message("部署标识缺失，请重新安装控制台") }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("FirstLightReplayBridge/" + id + "/jobs", isDirectory: true)
    }
    static func readExactly(_ handle: FileHandle, _ count: Int) throws -> Data {
        var result = Data()
        while result.count < count {
            guard let data = try handle.read(upToCount: count - result.count), !data.isEmpty else { throw BridgeError.message("本地消息未完整传输") }
            result.append(data)
        }
        return result
    }
    static func jobID(_ value: Any?) throws -> String {
        guard let text = value as? String, let uuid = UUID(uuidString: text), uuid.uuidString.lowercased() == text else { throw BridgeError.message("任务编号不正确") }
        return text
    }
    static func sourceURL(_ value: Any?) throws -> (String, String) {
        guard let text = value as? String, text.count <= 4096, let url = URLComponents(string: text), url.scheme == "https",
              ["royaleapi.com", "www.royaleapi.com"].contains(url.host ?? ""), url.user == nil, url.password == nil,
              url.port == nil || url.port == 443, url.path == "/replay" || url.path == "/replay/" else { throw BridgeError.message("只接受 RoyaleAPI HTTPS 回放详情") }
        let tags = (url.queryItems ?? []).filter { $0.name == "tag" }
        guard tags.count == 1, let tag = tags[0].value, tag.range(of: "^[A-Z0-9]{6,32}$", options: .regularExpression) != nil else { throw BridgeError.message("缺少唯一回放编号") }
        var clean = URLComponents(); clean.scheme = "https"; clean.host = "royaleapi.com"; clean.path = "/replay"
        clean.queryItems = (url.queryItems ?? []).filter { ["tag", "team_tags", "opponent_tags", "team_crowns", "opponent_crowns"].contains($0.name) }
        return (tag, clean.string!)
    }
    static func save(_ object: [String: Any], _ path: URL) throws {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        try data.write(to: path, options: [.atomic])
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
    static func launch() throws {
        guard NSWorkspace.shared.open(app) else { throw BridgeError.message("无法打开桌面回放控制台，请自行打开后再试") }
    }
    static func handle(_ message: [String: Any]) throws -> [String: Any] {
        let directory = try queue()
        switch message["command"] as? String {
        case "status":
            let id = try jobID(message["job_id"])
            let path = directory.appendingPathComponent(id + ".status.json")
            if let data = try? Data(contentsOf: path), data.count <= 65536,
               var status = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                status["ok"] = true; return status
            }
            return ["ok": true, "job_id": id, "state": "missing", "message": "没有找到此任务，请重新发送回放。"]
        case "launch": try launch(); return ["ok": true]
        case "capture-play":
            let (tag, url) = try sourceURL(message["url"])
            guard let html = message["html"] as? String, let raw = html.data(using: .utf8), !raw.isEmpty, raw.count <= 25 * 1024 * 1024,
                  html.contains("data-t="), html.contains("data-c="), html.contains("data-tag=") else { throw BridgeError.message("当前页没有完整回放 HTML，或超过25MB") }
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let id = UUID().uuidString.lowercased()
            let htmlPath = directory.appendingPathComponent(id + ".html")
            try raw.write(to: htmlPath, options: [.atomic])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: htmlPath.path)
            let digest = SHA256.hash(data: raw).map { String(format: "%02x", $0) }.joined()
            try save(["ok": true, "job_id": id, "state": "queued", "message": "HTML 已送到本机，等待控制台校验并播放。"], directory.appendingPathComponent(id + ".status.json"))
            try save(["schema": "official-web-replay.bridge-job.v1", "job_id": id, "command": "capture-play", "replay_tag": tag,
                      "source_url": url, "source_sha256": digest], directory.appendingPathComponent(id + ".json"))
            // Once committed, a launcher failure must not be reported as a
            // failed download: a running console may already claim this job.
            var warning = ""
            do { try launch() } catch { warning = "HTML 已保存，但无法自动打开控制台，请自行打开。" }
            return ["ok": true, "job_id": id, "state": "queued", "launch_warning": warning]
        default: throw BridgeError.message("不支持的本地桥接操作")
        }
    }
}

@main
struct ReplayBridgeMain {
    static func main() {
        var response: [String: Any]
        do {
            guard CommandLine.arguments.count >= 2, CommandLine.arguments[1] == Bridge.origin else { throw BridgeError.message("未授权的扩展来源") }
            let header = try Bridge.readExactly(.standardInput, 4)
            let size = header.enumerated().reduce(UInt32(0)) { $0 | UInt32($1.element) << (8 * $1.offset) }
            guard size > 0 && size <= 64 * 1024 * 1024 else { throw BridgeError.message("本地消息大小无效") }
            let raw = try Bridge.readExactly(.standardInput, Int(size))
            guard let message = try JSONSerialization.jsonObject(with: raw) as? [String: Any] else { throw BridgeError.message("本地消息格式无效") }
            response = try Bridge.handle(message)
        } catch { response = ["ok": false, "error": String(error.localizedDescription.prefix(2000))] }
        guard let data = try? JSONSerialization.data(withJSONObject: response), data.count < 1024 * 1024 else { return }
        let size = UInt32(data.count)
        let header = Data((0..<4).map { UInt8(truncatingIfNeeded: size >> (8 * $0)) })
        try? FileHandle.standardOutput.write(contentsOf: header + data)
    }
}
