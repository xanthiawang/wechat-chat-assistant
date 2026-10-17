import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct ImportRow: Codable, Identifiable {
    var row_id: Int
    var selected: Bool
    var title: String
    var contact: String
    var topic: String
    var category: String
    var due_original: String
    var details: String
    var status: String
    var new_instance: Bool
    var existing_status: String?
    var id: Int { row_id }
}

@MainActor final class TaskImportState: ObservableObject {
    @Published var text = ""
    @Published var format = "text"
    @Published var sourceName = "粘贴内容"
    @Published var rows: [ImportRow] = []
    @Published var token = ""
    @Published var busy = false
    @Published var message = "每行一件事。日期保留原话，不会把“明天”擅自变成截止日。"
    @Published var saved = false
    let home: URL
    let package: URL
    let python: String
    init(home: URL, package: URL, python: String) { self.home=home; self.package=package; self.python=python }
    func chooseFile() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection=false; panel.canChooseDirectories=false
        panel.allowedContentTypes=[.plainText,.commaSeparatedText,.json,UTType(filenameExtension:"md") ?? .plainText]
        guard panel.runModal() == .OK, let file=panel.url else { return }
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath:file.path)
            guard ((attributes[.size] as? NSNumber)?.intValue ?? 0) <= 1_000_000 else { message="文件不超过1MB，请拆分后导入。"; return }
            text=try String(contentsOf:file,encoding:.utf8); sourceName=file.lastPathComponent
            format=["csv","json","md"].contains(file.pathExtension.lowercased()) ? file.pathExtension.lowercased() : "text"
            rows=[];token="";saved=false;message="文件已读取，请点预览。保存之前可逐项修改或取消选择。"
        } catch { message="无法读取文件。请使用UTF-8格式的TXT、Markdown、CSV或JSON。" }
    }
    func request(_ value: [String:Any], completion: @escaping ([String:Any])->Void) {
        guard !busy else { return };busy=true
        do {
            let input=try JSONSerialization.data(withJSONObject:value)
            let process=Process();process.executableURL=URL(fileURLWithPath:python)
            process.arguments=[package.appendingPathComponent("app/task_import.py").path]
            process.environment=ProcessInfo.processInfo.environment.merging(["WECHAT_ASSISTANT_HOME":home.path]) { _,new in new }
            let stdin=Pipe(),output=Pipe();process.standardInput=stdin;process.standardOutput=output;process.standardError=output
            try process.run()
            DispatchQueue.global(qos:.userInitiated).async {
                stdin.fileHandleForWriting.write(input);try? stdin.fileHandleForWriting.close()
                let data=output.fileHandleForReading.readDataToEndOfFile();process.waitUntilExit()
                let result=try? JSONSerialization.jsonObject(with:data) as? [String:Any]
                DispatchQueue.main.async {
                    self.busy=false
                    if let result=result {
                        if process.terminationStatus==0 { completion(result) }
                        else { self.message=result["message"] as? String ?? "导入未完成，原待办保持原状。" }
                    } else { self.message="没有取得有效导入结果。不要重复新建同名任务，请先刷新查看状态。" }
                }
            }
        } catch { busy=false;message="无法开始导入：\(error.localizedDescription)" }
    }
    func preview() {
        request(["action":"preview","text":text,"format":format,"source_name":sourceName]) { value in
            do {
                let data=try JSONSerialization.data(withJSONObject:value["rows"] ?? [])
                self.rows=try JSONDecoder().decode([ImportRow].self,from:data)
                self.token=value["token"] as? String ?? ""
                self.message=value["notice"] as? String ?? "请核对后保存。"
            } catch { self.message="预览格式不完整，未保存待办。" }
        }
    }
    func commit() {
        do {
            let data=try JSONEncoder().encode(rows);let values=try JSONSerialization.jsonObject(with:data)
            request(["action":"commit","token":token,"owner_confirmed":true,"rows":values]) { value in
                let added=(value["added"] as? [String])?.count ?? 0
                let duplicates=(value["duplicates"] as? [String])?.count ?? 0
                self.message="已新增 \(added) 项，\(duplicates) 项重复记录保留原状态。完成的事项不会重新打开。"
                self.saved=true
            }
        } catch { message="无法读取预览内容，尚未保存。" }
    }
}

struct TaskImportView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model: TaskImportState
    let onSaved: () -> Void
    init(home:URL,package:URL,python:String,onSaved:@escaping ()->Void) {
        _model=StateObject(wrappedValue:TaskImportState(home:home,package:package,python:python));self.onSaved=onSaved
    }
    var body: some View {
        VStack(alignment:.leading,spacing:16) {
            HStack {
                VStack(alignment:.leading,spacing:5) { Text("导入待办").font(.title2.bold()); Text("选择来源 → 预览修改 → 本人确认保存。整个导入不调用模型。 ").foregroundStyle(.secondary) }
                Spacer();Button("关闭") { if model.saved { onSaved() };dismiss() }.disabled(model.busy)
            }
            if model.rows.isEmpty {
                HStack {
                    Button("选择文件…") { model.chooseFile() }
                    Picker("格式",selection:$model.format) { Text("每行一条 / TXT").tag("text");Text("Markdown").tag("md");Text("CSV").tag("csv");Text("JSON").tag("json") }.frame(width:265)
                    Spacer();Text(model.sourceName).font(.caption).foregroundStyle(.secondary)
                }
                TextEditor(text:$model.text).font(.body).padding(8).overlay(RoundedRectangle(cornerRadius:8).stroke(.quaternary)).frame(minHeight:330)
                Text("CSV可用事项、联系人、项目、责任、日期、说明列。文件里的完成标记不会自动生效；在下一步由你确认状态。最多200项、1MB。").font(.caption).foregroundStyle(.secondary)
                Button(model.busy ? "预览中…" : "预览并核对") { model.preview() }.buttonStyle(.borderedProminent).disabled(model.busy || model.text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
            } else {
                HStack { Text("共 \(model.rows.count) 项，选中 \(model.rows.filter(\.selected).count) 项").fontWeight(.medium);Spacer();Button("返回修改来源") { model.rows=[];model.token="" }.disabled(model.busy || model.saved) }
                ScrollView {
                    LazyVStack(spacing:12) {
                        ForEach($model.rows) { $row in
                            VStack(alignment:.leading,spacing:9) {
                                HStack {
                                    Toggle("",isOn:$row.selected).labelsHidden()
                                    TextField("事项名称",text:$row.title)
                                    Picker("状态",selection:$row.status) { Text("未完成").tag("open");Text("本人确认已完成").tag("done") }.frame(width:190)
                                }
                                HStack { TextField("联系人（可留空）",text:$row.contact);TextField("项目／主题",text:$row.topic) }
                                HStack {
                                    Picker("责任",selection:$row.category) { Text("我来处理").tag("self");Text("等对方推进").tag("followup");Text("待确认").tag("confirm") }.frame(width:230)
                                    TextField("日期／期限原话（可留空）",text:$row.due_original)
                                }
                                TextField("说明与下一步",text:$row.details)
                                HStack {
                                    Toggle("同名但确实是另一件事，单独保存",isOn:$row.new_instance).font(.caption)
                                    Spacer()
                                    if let state=row.existing_status { Text("已有记录："+(["open":"未完成","done":"已完成","cancelled":"已取消"][state] ?? "待核对")).font(.caption).foregroundStyle(.secondary) }
                                }
                            }.textFieldStyle(.roundedBorder).padding(13).overlay(RoundedRectangle(cornerRadius:10).stroke(.quaternary))
                        }
                    }.padding(2)
                }.disabled(model.busy || model.saved)
                HStack {
                    if model.saved { Button("完成") { onSaved();dismiss() }.buttonStyle(.borderedProminent) }
                    else { Button(model.busy ? "保存中…" : "我已核对，保存选中事项") { model.commit() }.buttonStyle(.borderedProminent).disabled(model.busy || !model.rows.contains(where:\.selected)) }
                    Spacer();Text("已有任务的完成状态不会被导入覆盖。").font(.caption).foregroundStyle(.secondary)
                }
            }
            Text(model.message).font(.callout).foregroundStyle(model.saved ? .green : .secondary).textSelection(.enabled)
        }.padding(24).frame(minWidth:840,minHeight:650)
    }
}
