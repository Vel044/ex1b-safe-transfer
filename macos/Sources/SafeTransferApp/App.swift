import SwiftUI
import AppKit
import SafeTransferCore

@main
struct SafeTransferApplication: App {
    @StateObject private var model = AppModel()
    var body: some Scene {
        WindowGroup("安传") { MainWindow(model:model).frame(minWidth:1000,minHeight:680) }
            .defaultSize(width:1220,height:800).windowToolbarStyle(.unified)
            .commands {
                CommandGroup(after:.newItem) {
                    Button("选择本地目录…"){model.chooseRoot()}.keyboardShortcut("o")
                    Button("连接服务器…"){model.showConnection=true}.keyboardShortcut("k")
                }
                CommandGroup(after:.toolbar) { Button("刷新文件列表"){model.refresh()}.keyboardShortcut("r") }
            }
        Settings {
            Form {
                Text("安传 安全文件传输").font(.headline)
                LabeledContent("客户端",value:"SwiftUI · AppKit · Network.framework")
                LabeledContent("协议",value:"SFT1 / 双向TLS / SHA-256")
                Text("每个账户最多4个并发文件；同名文件拒绝覆盖。证书密码不写入配置或任务记录。").foregroundStyle(.secondary)
                Button("连接设置…"){model.showConnection=true;NSApp.activate(ignoringOtherApps:true)}
            }.formStyle(.grouped).padding().frame(width:480)
        }
    }
}

struct FileRow:Identifiable,Sendable {
    let name:String; let directory:Bool; let size:Int64; let modified:Date
    var id:String{name}
    var sizeText:String{directory ? "—" : ByteCountFormatter.string(fromByteCount:size,countStyle:.file)}
}

@MainActor final class AppModel:ObservableObject {
    @Published var session=SessionSnapshot()
    @Published var jobs:[TransferSnapshot]=[]
    @Published var local:[FileRow]=[]
    @Published var remote:[FileRow]=[]
    @Published var root:URL?
    @Published var localPath=""
    @Published var remotePath=""
    @Published var localSelection:Set<String>=[]
    @Published var remoteSelection:Set<String>=[]
    @Published var jobSelection:Set<String>=[]
    @Published var showConnection=false
    @Published var errorText:String?
    @Published var notice="选择本地目录并连接服务器，即可开始传输"
    @Published var working=false
    let engine:TransferEngine
    let disk=DiskWorker()
    private var scopes:[URL]=[]
    private var completeCount=0

    init() {
        do{engine=TransferEngine(store:try TaskStore())}
        catch{let alert=NSAlert();alert.messageText="无法打开任务数据库";alert.informativeText=error.localizedDescription;alert.runModal();fatalError("Task store unavailable")}
        if let data=UserDefaults.standard.data(forKey:"localBookmark") {
            var stale=false
            if let url=try? URL(resolvingBookmarkData:data,options:[.withSecurityScope],relativeTo:nil,bookmarkDataIsStale:&stale),!stale,url.startAccessingSecurityScopedResource(){root=url}
        }
        Task{[weak self] in
            guard let self else{return}
            do{try await engine.initialize()}catch{errorText=error.localizedDescription}
            await refreshLocal()
            while !Task.isCancelled {
                session=await engine.session()
                if let tasks=try? await engine.tasks(){
                    jobs=tasks
                    let count=tasks.filter{$0.status == "complete"}.count
                    if count != completeCount{completeCount=count;await refreshLocal();if session.connected{await refreshRemote()}}
                }
                try? await Task.sleep(for:.milliseconds(500))
            }
        }
    }
    func chooseRoot(){
        let panel=NSOpenPanel();panel.title="选择允许安传访问的本地目录";panel.canChooseDirectories=true;panel.canChooseFiles=false
        guard panel.runModal() == .OK,let url=panel.url else{return}
        do{
            let data=try url.bookmarkData(options:.withSecurityScope,includingResourceValuesForKeys:nil,relativeTo:nil)
            root?.stopAccessingSecurityScopedResource();_ = url.startAccessingSecurityScopedResource()
            root=url;localPath="";localSelection=[];UserDefaults.standard.set(data,forKey:"localBookmark")
            Task{await refreshLocal()}
        }catch{errorText=error.localizedDescription}
    }
    func refresh(){Task{await refreshLocal();if session.connected{await refreshRemote()}}}
    func refreshLocal()async{
        guard let root else{return};let path=localPath
        do{
            let rows=try await disk.run{()->[FileRow] in
                let pieces=try Disk.segments(path,rootAllowed:true)
                return try Disk.withDirectory(root:root,pieces:pieces){_ in
                    let url=pieces.reduce(root){$0.appendingPathComponent($1)}
                    return try FileManager.default.contentsOfDirectory(at:url,includingPropertiesForKeys:[.isDirectoryKey,.isSymbolicLinkKey,.isRegularFileKey,.fileSizeKey,.contentModificationDateKey],options:.skipsHiddenFiles).compactMap{url in
                        let info=try url.resourceValues(forKeys:[.isDirectoryKey,.isSymbolicLinkKey,.isRegularFileKey,.fileSizeKey,.contentModificationDateKey])
                        guard info.isSymbolicLink != true,info.isDirectory == true || info.isRegularFile == true else{return nil}
                        return FileRow(name:url.lastPathComponent,directory:info.isDirectory == true,size:Int64(info.fileSize ?? 0),modified:info.contentModificationDate ?? .distantPast)
                    }.sorted{$0.directory != $1.directory ? $0.directory : $0.name.localizedStandardCompare($1.name) == .orderedAscending}
                }
            }
            if localPath == path{local=rows}
        }catch{errorText=error.localizedDescription}
    }
    func refreshRemote()async{
        let path=remotePath
        do{let rows=try await engine.list(path).map{FileRow(name:$0.name,directory:$0.directory,size:$0.size,modified:$0.modified)};if remotePath == path{remote=rows}}
        catch{if session.connected{errorText=error.localizedDescription}}
    }
    func open(_ ids:Set<String>,localSide:Bool){
        guard ids.count == 1,let name=ids.first,(localSide ? local : remote).first(where:{$0.name == name})?.directory == true else{return}
        if localSide{localPath=TransferEngine.join(localPath,name);localSelection=[];Task{await refreshLocal()}}
        else{remotePath=TransferEngine.join(remotePath,name);remoteSelection=[];Task{await refreshRemote()}}
    }
    func up(_ localSide:Bool){
        if localSide{localPath=localPath.components(separatedBy:"/").dropLast().joined(separator:"/");localSelection=[];Task{await refreshLocal()}}
        else{remotePath=remotePath.components(separatedBy:"/").dropLast().joined(separator:"/");remoteSelection=[];Task{await refreshRemote()}}
    }
    func connect(_ credentials:Credentials,scopes:[URL])async throws{
        for url in self.scopes{url.stopAccessingSecurityScopedResource()};self.scopes=scopes
        try await engine.connect(credentials);session=await engine.session();remotePath="";remoteSelection=[]
        await refreshRemote();notice="已连接为 \(session.user)，可多选文件或文件夹上传下载"
    }
    func disconnect(){Task{await engine.disconnect();session=await engine.session();remote=[]}}
    func transfer(upload:Bool){
        guard let root else{return}
        let selectedRoot=localPath.components(separatedBy:"/").filter{!$0.isEmpty}.reduce(root){$0.appendingPathComponent($1)}
        let localNames=localSelection.sorted(),remoteNames=remoteSelection
        let remoteDirectory=remotePath
        let entries=remote.filter{remoteNames.contains($0.name)}.map{RemoteEntry(name:$0.name,directory:$0.directory,size:$0.size,modified:$0.modified)}
        working=true
        Task{
            defer{working=false}
            do{
                let bookmark=try selectedRoot.bookmarkData(options:.withSecurityScope,includingResourceValuesForKeys:nil,relativeTo:nil)
                if upload{
                    let warnings=try await engine.enqueueUploads(root:selectedRoot,paths:localNames,remoteDirectory:remoteDirectory,bookmark:bookmark)
                    notice=warnings.isEmpty ? "已加入上传队列" : warnings.joined(separator:"；")
                }else{try await engine.enqueueDownloads(entries:entries,remoteDirectory:remoteDirectory,root:selectedRoot,bookmark:bookmark);notice="已加入下载队列"}
            }catch{errorText=error.localizedDescription}
        }
    }
    func mkdir(_ localSide:Bool){
        let alert=NSAlert();alert.messageText="新建\(localSide ? "本地" : "远端")目录";alert.addButton(withTitle:"创建");alert.addButton(withTitle:"取消")
        let field=NSTextField(frame:NSRect(x:0,y:0,width:280,height:24));field.placeholderString="目录名称";alert.accessoryView=field;alert.window.initialFirstResponder=field
        guard alert.runModal() == .alertFirstButtonReturn else{return};let name=field.stringValue
        Task{do{
            guard try Disk.segments(name).count == 1 else{throw TransferFault("INPUT","请输入单个目录名称")}
            if localSide,let root{let path=TransferEngine.join(localPath,name);try await disk.run{try Disk.makeDirectories(root:root,path:path)};await refreshLocal()}
            else{try await engine.mkdir(TransferEngine.join(remotePath,name));await refreshRemote()}
        }catch{errorText=error.localizedDescription}}
    }
    func taskAction(_ action:String,group:Bool=false){
        var ids=jobSelection
        if group{let groups=Set(jobs.filter{ids.contains($0.id)}.map(\.group));ids=Set(jobs.filter{groups.contains($0.group)}.map(\.id))}
        Task{do{try await engine.action(action,ids:ids)}catch{errorText=error.localizedDescription}}
    }
}

struct MainWindow:View {
    @ObservedObject var model:AppModel
    var body:some View {
        VStack(spacing:0){
            VSplitView{
                HSplitView{filePane(true).frame(minWidth:320);filePane(false).frame(minWidth:320)}.frame(minHeight:280)
                queue.frame(minHeight:170,idealHeight:250)
            }
            Divider()
            HStack(spacing:12){
                Image(systemName:model.session.connected ? "lock.shield.fill" : "network.slash").foregroundStyle(model.session.connected ? Color.green : Color.secondary)
                Text(model.session.connected ? "\(model.session.user) · 双向TLS · \(ByteCountFormatter.string(fromByteCount:model.session.bandwidth,countStyle:.binary))/s" : model.session.detail).lineLimit(1)
                Spacer();if model.working{ProgressView().controlSize(.small)}
                Text(model.notice).foregroundStyle(.secondary).lineLimit(1)
            }.font(.caption).padding(.horizontal,14).padding(.vertical,8)
        }
        .toolbar{
            ToolbarItemGroup(placement:.navigation){
                Button{model.showConnection=true}label:{Label("连接",systemImage:"network")}.help("连接服务器 ⌘K")
                if model.session.connected{Button{model.disconnect()}label:{Label("断开",systemImage:"eject")}}
            }
            ToolbarItemGroup{
                Button{model.transfer(upload:true)}label:{Label("上传",systemImage:"arrow.up.doc")}.disabled(!model.session.connected || model.localSelection.isEmpty || model.working)
                Button{model.transfer(upload:false)}label:{Label("下载",systemImage:"arrow.down.doc")}.disabled(!model.session.connected || model.remoteSelection.isEmpty || model.root == nil || model.working)
                Button{model.refresh()}label:{Label("刷新",systemImage:"arrow.clockwise")}
            }
        }
        .sheet(isPresented:$model.showConnection){ConnectionSheet(model:model)}
        .alert("操作未完成",isPresented:Binding(get:{model.errorText != nil},set:{if !$0{model.errorText=nil}})){Button("好",role:.cancel){model.errorText=nil}}message:{Text(model.errorText ?? "")}
    }
    private func filePane(_ local:Bool)->some View{
        VStack(spacing:0){
            HStack{
                Label(local ? "本地文件" : "服务器文件",systemImage:local ? "internaldrive" : "server.rack").font(.headline);Spacer()
                if local{Button("选择目录…"){model.chooseRoot()}}
                Button{model.up(local)}label:{Image(systemName:"arrow.up")}.disabled(local ? model.localPath.isEmpty : model.remotePath.isEmpty).help("上一级目录")
                Button{model.mkdir(local)}label:{Image(systemName:"folder.badge.plus")}.disabled(local ? model.root == nil : !model.session.connected).help("新建目录")
            }.padding(10)
            HStack{Image(systemName:"folder");Text(local ? (model.root?.lastPathComponent ?? "未选择目录")+(model.localPath.isEmpty ? "" : "/"+model.localPath) : "/"+model.remotePath).lineLimit(1).truncationMode(.middle).textSelection(.enabled);Spacer()}.font(.caption).foregroundStyle(.secondary).padding(.horizontal,12).padding(.bottom,8)
            Divider()
            if local && model.root == nil{
                ContentUnavailableView{Label("选择本地目录",systemImage:"folder")}description:{Text("通过系统选择器授权上传来源及下载位置")}actions:{Button("选择目录…"){model.chooseRoot()}}
            }else if !local && !model.session.connected{
                ContentUnavailableView{Label("尚未连接",systemImage:"server.rack")}description:{Text("使用证书连接安全文件服务器")}actions:{Button("连接服务器…"){model.showConnection=true}}
            }else{
                Table(local ? model.local : model.remote,selection:local ? $model.localSelection : $model.remoteSelection){
                    TableColumn("名称"){row in Label(row.name,systemImage:row.directory ? "folder.fill" : "doc").foregroundStyle(row.directory ? Color.accentColor : Color.primary)}.width(min:140,ideal:240)
                    TableColumn("大小"){Text($0.sizeText).monospacedDigit()}.width(min:65,ideal:80)
                    TableColumn("修改时间"){Text($0.modified,format:.dateTime.month().day().hour().minute()).foregroundStyle(.secondary)}.width(min:100,ideal:125)
                }.contextMenu(forSelectionType:String.self){ids in
                    Button("打开目录"){model.open(ids,localSide:local)}.disabled(ids.count != 1)
                    Button(local ? "上传所选项目" : "下载所选项目"){model.transfer(upload:local)}.disabled(!model.session.connected || ids.isEmpty)
                }primaryAction:{ids in model.open(ids,localSide:local)}
            }
        }
    }
    private var queue:some View{
        VStack(spacing:0){
            HStack{
                Label("传输队列",systemImage:"arrow.up.arrow.down").font(.headline)
                Text("\(model.jobs.filter{$0.status == "complete"}.count) / \(model.jobs.count) 已完成").font(.caption).foregroundStyle(.secondary);Spacer()
                Group{
                    Button{model.taskAction("pause")}label:{Label("暂停",systemImage:"pause")}
                    Button{model.taskAction("resume")}label:{Label("继续",systemImage:"play")}.disabled(!model.session.connected)
                    Button{model.taskAction("cancel")}label:{Label("取消",systemImage:"xmark")}
                    Menu("整组任务"){
                        Button("暂停所选文件夹"){model.taskAction("pause",group:true)}
                        Button("继续所选文件夹"){model.taskAction("resume",group:true)}
                        Button("取消所选文件夹"){model.taskAction("cancel",group:true)}
                    }
                }.disabled(model.jobSelection.isEmpty)
            }.controlSize(.small).padding(10)
            Divider()
            if model.jobs.isEmpty{ContentUnavailableView("传输队列为空",systemImage:"tray",description:Text("多选文件或文件夹，然后点击上传或下载"))}
            else{
                Table(model.jobs,selection:$model.jobSelection){
                    TableColumn("文件 / 目录"){task in HStack{
                        Image(systemName:task.directory ? "folder" : task.direction == "upload" ? "arrow.up.doc" : "arrow.down.doc")
                        VStack(alignment:.leading,spacing:2){Text(task.remotePath).lineLimit(1).truncationMode(.middle);Text(task.groupName).font(.caption2).foregroundStyle(.secondary)}
                    }}.width(min:220,ideal:350)
                    TableColumn("进度"){task in HStack{ProgressView(value:task.progress);Text(task.progress,format:.percent.precision(.fractionLength(0))).monospacedDigit().frame(width:38,alignment:.trailing)}}.width(min:140,ideal:200)
                    TableColumn("大小"){Text(ByteCountFormatter.string(fromByteCount:$0.size,countStyle:.file)).monospacedDigit()}.width(85)
                    TableColumn("速度"){Text($0.speed > 0 ? ByteCountFormatter.string(fromByteCount:Int64($0.speed),countStyle:.binary)+"/s" : "—").monospacedDigit()}.width(100)
                    TableColumn("状态"){task in Text(task.statusText).foregroundStyle(task.status == "failed" ? Color.red : Color.primary)}.width(90)
                }
                if let selected=model.jobs.first(where:{model.jobSelection.contains($0.id)}),!selected.detail.isEmpty{
                    HStack{Image(systemName:selected.status == "failed" ? "exclamationmark.triangle" : "info.circle");Text(selected.detail).textSelection(.enabled);Spacer()}.font(.caption).padding(.horizontal,10).padding(.vertical,6)
                }
            }
        }
    }
}

struct ConnectionSheet:View{
    @ObservedObject var model:AppModel
    @Environment(\.dismiss) var dismiss
    @State private var host=UserDefaults.standard.string(forKey:"host") ?? "localhost"
    @State private var port=UserDefaults.standard.string(forKey:"port") ?? "8443"
    @State private var ca:URL?
    @State private var identity:URL?
    @State private var password=""
    @State private var busy=false
    @State private var error=""
    @State private var scopes:[URL]=[]
    var body:some View{
        VStack(alignment:.leading,spacing:16){
            Label("连接安全文件服务器",systemImage:"lock.shield").font(.title2)
            Form{
                TextField("服务器",text:$host).textFieldStyle(.roundedBorder)
                TextField("端口",text:$port).textFieldStyle(.roundedBorder)
                LabeledContent("CA证书"){Text(ca?.lastPathComponent ?? "未选择").foregroundStyle(.secondary);Button("选择…"){pick(false)}}
                LabeledContent("客户端身份"){Text(identity?.lastPathComponent ?? "未选择P12").foregroundStyle(.secondary);Button("选择…"){pick(true)}}
                SecureField("P12密码",text:$password).textFieldStyle(.roundedBorder)
            }
            Text("双向验证证书，账户由客户端身份决定。密码只用于读取P12，不写入配置或任务记录。").font(.caption).foregroundStyle(.secondary)
            if !error.isEmpty{Text(error).foregroundStyle(.red).font(.callout).textSelection(.enabled)}
            HStack{
                if busy{ProgressView().controlSize(.small);Text("正在验证证书…").foregroundStyle(.secondary)};Spacer()
                Button("取消",role:.cancel){for url in scopes{url.stopAccessingSecurityScopedResource()};dismiss()}.keyboardShortcut(.cancelAction).disabled(busy)
                Button("连接"){connect()}.keyboardShortcut(.defaultAction).disabled(busy || ca == nil || identity == nil || password.isEmpty)
            }
        }.padding(24).frame(width:490)
        .onAppear{restore("caBookmark",false);restore("identityBookmark",true)}
    }
    private func restore(_ key:String,_ identityFile:Bool){
        guard let data=UserDefaults.standard.data(forKey:key) else{return};var stale=false
        guard let url=try? URL(resolvingBookmarkData:data,options:[.withSecurityScope],relativeTo:nil,bookmarkDataIsStale:&stale),!stale else{return}
        _ = url.startAccessingSecurityScopedResource();scopes.append(url);if identityFile{identity=url}else{ca=url}
    }
    private func pick(_ identityFile:Bool){
        let panel=NSOpenPanel();panel.title=identityFile ? "选择客户端P12身份" : "选择实验CA证书";panel.canChooseDirectories=false
        guard panel.runModal() == .OK,let url=panel.url else{return};_ = url.startAccessingSecurityScopedResource();scopes.append(url)
        do{UserDefaults.standard.set(try url.bookmarkData(options:.withSecurityScope,includingResourceValuesForKeys:nil,relativeTo:nil),forKey:identityFile ? "identityBookmark" : "caBookmark");if identityFile{identity=url;password=""}else{ca=url}}
        catch{self.error=error.localizedDescription}
    }
    private func connect(){
        guard let ca,let identity,let portNumber=UInt16(port),portNumber>0,!host.isEmpty else{error="请输入有效的服务器和端口";return}
        busy=true;error=""
        Task{do{
            try await model.connect(Credentials(host:host,port:portNumber,ca:ca,identity:identity,password:password),scopes:scopes)
            UserDefaults.standard.set(host,forKey:"host");UserDefaults.standard.set(port,forKey:"port");password="";scopes=[];dismiss()
        }catch{self.error=error.localizedDescription;busy=false}}
    }
}
