import SwiftUI
import AppKit

@MainActor final class AssistantState: ObservableObject {
    @Published var status: [String: Any] = [:]
    @Published var checking = false
    @Published var activity = "选择一个步骤，授权将在终端中由你本人完成。"
    let readOnly = CommandLine.arguments.contains("--read-only")
    let home: URL
    let package: URL
    private var operation: URL?
    private var timer: Timer?
    private var configuration: [String: Any] {
        guard let data = try? Data(contentsOf: home.appendingPathComponent("reader-config.json")),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return value
    }
    init() {
        let path = ProcessInfo.processInfo.environment["WECHAT_ASSISTANT_HOME"]
        home = path.map { URL(fileURLWithPath: $0).standardizedFileURL }
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/share/wechat-chat-assistant")
        package = Bundle.main.resourceURL!.appendingPathComponent("package")
        if configuration.isEmpty { status = ["installed": false] } else { refresh() }
    }
    var installed: Bool { !configuration.isEmpty }
    var connected: Bool { configuration["account"] != nil && configuration["owner"] != nil }
    var reader: Bool { configuration["reader_verified"] as? Bool == true && configuration["original_app_confirmed"] as? Bool == true }
    var schedules: [String: Any] { status["schedules"] as? [String: Any] ?? [:] }
    var daily: [String: Any] { schedules["daily_job_id"] as? [String: Any] ?? [:] }
    var dailyEnabled: Bool { daily["enabled"] as? Bool == true }
    var warnings: [String] { status["warnings"] as? [String] ?? [] }
    var sourceDay: String { (status["latest_briefing"] as? [String: Any])?["source_day"] as? String ?? "尚未检查" }
    var reportState: String {
        let value = (status["latest_briefing"] as? [String: Any])?["status"] as? String ?? "unknown"
        return ["sent":"已发送", "corrected_sent":"更正版已发送", "ready":"已准备，等待投递", "reading":"读取中或上次中断", "reading_failed":"读取失败", "summarizing":"总结中或上次中断", "not_prepared":"尚未生成", "delivery_unknown":"投递结果待核对", "delivery_pending":"投递中或结果待核对" ][value] ?? "尚未检查或结果待确认"
    }
    func python() -> String? {
        if let path = configuration["python"] as? String, FileManager.default.isExecutableFile(atPath: path) { return path }
        return ["/opt/homebrew/bin/python3.14", "/usr/local/bin/python3.14"].first { FileManager.default.isExecutableFile(atPath: $0) }
    }
    func refresh() {
        guard !checking else { return }
        guard installed, let executable = python() else {
            status = ["installed": installed]
            activity = installed ? "未找到安装时的 Python，请先恢复依赖。" : "尚未安装。先完成第 1 步。"
            return
        }
        checking = true
        let task = Process()
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = [package.appendingPathComponent("app/setup.py").path, "doctor"]
        task.environment = ProcessInfo.processInfo.environment.merging(["WECHAT_ASSISTANT_HOME":home.path]) { _, new in new }
        let output = Pipe(), errors = Pipe()
        task.standardOutput = output; task.standardError = errors
        task.terminationHandler = { [weak self] process in
            let data = output.fileHandleForReading.readDataToEndOfFile()
            let _ = errors.fileHandleForReading.readDataToEndOfFile()
            let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            DispatchQueue.main.async {
                self?.checking = false
                if process.terminationStatus == 0, let result = result {
                    self?.status = result; self?.activity = "状态已刷新；不会试发消息或修改设置。"
                } else { self?.activity = "检查未完成，不能据此判断服务正常。可打开安装文档恢复。" }
            }
        }
        do { try task.run() } catch { checking = false; activity = "无法开始检查：\(error.localizedDescription)" }
    }
    private func quote(_ value: String) -> String { "'" + value.replacingOccurrences(of: "'", with: "'\"'\"'") + "'" }
    func run(_ command: String) {
        guard !readOnly, operation == nil else { return }
        do {
            let folder = home.appendingPathComponent("gui/actions/\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let script = folder.appendingPathComponent("Configure.command")
            let exitFile = folder.appendingPathComponent("exit-code")
            let argv: String
            if command == "install" {
                argv = "/bin/bash " + quote(package.appendingPathComponent("Install.command").path)
            } else {
                guard let executable = python() else { activity = "请先完成第 1 步，安装运行依赖。"; return }
                argv = quote(executable) + " " + quote(package.appendingPathComponent("app/setup.py").path) + " " + quote(command)
            }
            let text = """
            #!/bin/bash
            umask 077
            export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
            export WECHAT_ASSISTANT_HOME=\(quote(home.path))
            \(argv)
            result=$?
            printf '%s\\n' "$result" > \(quote(exitFile.path))
            echo
            if [ "$result" = 0 ]; then echo '此步骤已结束，请返回微信聊天助手刷新状态。'; else echo '此步骤未完成。现有配置和记录保留，请查看上方提示。'; fi
            read -r -p '按回车关闭此终端页。'
            exit "$result"
            """
            try text.write(to: script, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions:0o700], ofItemAtPath: script.path)
            let launcher = Process(); launcher.executableURL = URL(fileURLWithPath:"/usr/bin/open")
            launcher.arguments = ["-a", "Terminal", script.path]
            try launcher.run(); launcher.waitUntilExit()
            guard launcher.terminationStatus == 0 else { throw NSError(domain:"Assistant",code:1,userInfo:[NSLocalizedDescriptionKey:"无法打开终端"]) }
            operation = exitFile; activity = "配置已在终端打开。请完成其中的授权，勿重复启动同一步。"
            timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    guard let self = self, let file = self.operation,
                          let value = try? String(contentsOf:file,encoding:.utf8) else { return }
                    self.timer?.invalidate(); self.timer = nil; self.operation = nil
                    self.activity = value.trimmingCharacters(in:.whitespacesAndNewlines) == "0" ? "步骤已结束；正在检查实际状态。" : "步骤未完成，请查看终端提示。"
                    self.refresh()
                }
            }
        } catch { activity = "无法开始配置：\(error.localizedDescription)" }
    }
    func web(_ suffix: String) { NSWorkspace.shared.open(URL(string:"https://github.com/xanthiawang/wechat-chat-assistant/" + suffix)!) }
}

struct AssistantView: View {
    @StateObject private var model = AssistantState()
    private let accent = Color(red:0.05,green:0.48,blue:0.34)
    var body: some View {
        HStack(spacing:0) {
            VStack(alignment:.leading,spacing:22) {
                Image(systemName:"bubble.left.and.text.bubble.right.fill").font(.system(size:36)).foregroundStyle(accent)
                Text("微信聊天助手").font(.system(size:23,weight:.semibold))
                Text("让聊天变成\n清楚的下一步。").font(.system(size:18,weight:.medium)).lineSpacing(5)
                Text("聊天检索\n每日 09:00 简报\n待办与关系记忆").font(.system(size:13)).foregroundStyle(.secondary).lineSpacing(12)
                Spacer()
                Text("0.2.0 BETA · Apple Silicon").font(.system(size:10,weight:.medium)).foregroundStyle(.secondary)
                Button("安装文档") { model.web("blob/main/docs/RECOVERY.md") }.buttonStyle(.link)
                Button("隐私说明") { model.web("blob/main/SECURITY.md") }.buttonStyle(.link)
            }.padding(30).frame(width:235,alignment:.leading).background(Color(nsColor:.controlBackgroundColor))
            ScrollView {
                VStack(alignment:.leading,spacing:20) {
                    HStack {
                        VStack(alignment:.leading,spacing:6) {
                            Text("配置你的私人助手").font(.system(size:25,weight:.semibold))
                            Text("完成四步。已有安装可以继续，个人记录会保留。").foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button { model.refresh() } label: { Label(model.checking ? "检查中" : "刷新状态",systemImage:"arrow.clockwise") }.disabled(model.checking)
                    }
                    card("1", "安装与环境", "Homebrew、Python、Node 与独立后台服务。", model.installed ? "已有安装" : "待安装", model.installed, "开始／继续", "install")
                    card("2", "连接模型与微信", "本人登录订阅、微信扫码，并向机器人发送“你好”。", model.connected ? "已保存绑定" : "待连接", model.connected, "连接", "connect")
                    card("3", "接入聊天记录", "先完成官方备份；读取初始化需要单独确认。", model.reader ? "已保存读取验证" : "待验证", model.reader, "接入", "reader")
                    card("4", "验证与开启早报", "真实检索与完整简报试发通过后，才启用定时任务。", model.dailyEnabled ? "已启用 09:00" : "尚未确认启用", model.dailyEnabled, "验证并启用", "enable")
                    VStack(alignment:.leading,spacing:9) {
                        HStack { Text("运行状态").fontWeight(.semibold); Spacer(); Text(model.sourceDay).foregroundStyle(.secondary) }
                        Text("完整简报：" + model.reportState)
                        if let learning = model.status["learning"] as? [String:Any], let samples = learning["voice_samples"] as? Int {
                            Text("语气样本 \(samples) 条 · 修改候选 \(learning["observed_edit_candidates"] as? Int ?? 0) 条").foregroundStyle(.secondary)
                        }
                        if let at = model.status["checked_at"] as? String { Text("最近检查：" + at).font(.caption).foregroundStyle(.secondary) }
                        if model.daily["last_status"] as? String == "error" { Text("早报最近一次运行失败。开启调度不代表已经准时送达。").foregroundStyle(.orange) }
                        ForEach(model.warnings, id: \.self) { warning in Text(warning).font(.caption).foregroundStyle(.secondary) }
                        Text(model.activity).font(.caption).foregroundStyle(.secondary)
                    }.padding(16).frame(maxWidth:.infinity,alignment:.leading).background(Color(nsColor:.controlBackgroundColor),in:RoundedRectangle(cornerRadius:12))
                    Text("记录与记忆保存在本机；总结内容发送给你授权的模型。电脑需保持开机联网。图片／语音尚不解析，代发消息不包含在此公开 Beta。扫码和读取授权仍会在终端中由你完成。").font(.caption).foregroundStyle(.secondary).lineSpacing(3)
                    if model.readOnly { Text("当前为只读检查模式，配置按钮已停用。").font(.caption).foregroundStyle(.secondary) }
                }.padding(30)
            }
        }.frame(minWidth:960,minHeight:760).tint(accent)
    }
    private func card(_ number:String,_ title:String,_ detail:String,_ badge:String,_ ready:Bool,_ action:String,_ command:String) -> some View {
        HStack(spacing:15) {
            Text(number).font(.system(size:17,weight:.semibold)).foregroundStyle(accent).frame(width:34,height:34).background(accent.opacity(0.09),in:Circle())
            VStack(alignment:.leading,spacing:6) { HStack { Text(title).font(.system(size:15,weight:.semibold)); Text(badge).font(.caption).foregroundStyle(ready ? accent : .secondary) }; Text(detail).font(.system(size:12)).foregroundStyle(.secondary) }
            Spacer()
            Button(action) { model.run(command) }.disabled(model.readOnly || (command != "install" && !model.installed))
        }.padding(15).overlay(RoundedRectangle(cornerRadius:12).stroke(Color(nsColor:.separatorColor).opacity(0.5)))
    }
}

@main struct WeChatAssistantApp: App {
    var body: some Scene { WindowGroup("微信聊天助手") { AssistantView() }.defaultSize(width:980,height:800).windowResizability(.contentMinSize) }
}
