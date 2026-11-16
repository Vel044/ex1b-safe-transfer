import Foundation
import CryptoKit

public struct RemoteEntry: Identifiable, Sendable {
    public let name: String
    public let directory: Bool
    public let size: Int64
    public let modified: Date
    public var id:String { name }
    public init(name:String,directory:Bool,size:Int64,modified:Date) {
        self.name=name; self.directory=directory; self.size=size; self.modified=modified
    }
}

public struct SessionSnapshot: Sendable {
    public var connected = false
    public var user = ""
    public var bandwidth: Int64 = 0
    public var detail = "尚未连接"
    public var heartbeats = 0
    public var connectionID = ""
    public init() {}
}

public actor TransferEngine {
    public let store: TaskStore
    private let disk = DiskWorker()
    private var connection: SecureConnection?
    private var credentials: Credentials?
    private var state = SessionSnapshot()
    private var endpoint = ""
    private var running: [String:Task<Void,Never>] = [:]
    private var controls: [String:String] = [:]
    private var heartbeat: Task<Void,Never>?
    private var reconnection: Task<Void,Never>?
    private var generation = 0
    private var scheduling = false

    public init(store:TaskStore) { self.store = store }
    public func session() -> SessionSnapshot { state }
    public func tasks() async throws -> [TransferSnapshot] { try await store.all() }
    public func initialize() async throws { try await store.recover() }

    public func connect(_ values:Credentials) async throws {
        await disconnect()
        credentials = values
        try await establish(values)
    }

    private func establish(_ values:Credentials) async throws {
        state.detail = "正在连接并验证双向证书…"
        let transport = SecureConnection()
        let welcome:Packet
        do { welcome = try await transport.connect(values) }
        catch { transport.disconnect(); state.detail = error.localizedDescription; throw error }
        connection = transport
        state.connected = true
        state.user = try welcome.meta.text("user")
        state.bandwidth = try welcome.meta.integer("bandwidth")
        state.detail = "双向证书已验证"
        state.connectionID = UUID().uuidString
        state.heartbeats = 0
        let ca = try Data(contentsOf:values.ca)
        endpoint = "\(values.host):\(values.port):" + SHA256.hash(data:ca).map { String(format:"%02x",$0) }.joined()
        heartbeat?.cancel()
        heartbeat = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for:.seconds(15))
                guard !Task.isCancelled, let self else { return }
                await self.checkHeartbeat()
            }
        }
        await schedule()
    }

    public func disconnect() async {
        generation += 1
        heartbeat?.cancel(); heartbeat = nil
        reconnection?.cancel(); reconnection = nil
        credentials = nil
        connection?.disconnect(); connection = nil
        state.connected = false; state.detail = "已断开"
        let current = running.values
        for task in current { task.cancel() }
        for task in current { await task.value }
    }

    private func checkHeartbeat() async {
        guard state.connected else { return }
        do {
            let response = try await call(.ping)
            state.heartbeats += 1
            if let rate = response.meta["bandwidth"]?.int { state.bandwidth = rate }
        } catch { await lost(error) }
    }

    private func call(_ kind:Message, meta:[String:WireValue] = [:], payload:Data = Data()) async throws -> Packet {
        guard let connection, state.connected else { throw TransferFault("DISCONNECTED","连接已断开，任务可在重连后继续") }
        for attempt in 0..<3 {
            do { return try await connection.request(kind,meta:meta,payload:payload,timeout:kind == .ping ? 10 : 60) }
            catch let fault as TransferFault where fault.code == "RATE" && attempt < 2 {
                try await Task.sleep(for:.milliseconds(1100))
            }
        }
        throw TransferFault("RATE","请求过于频繁")
    }

    private func lost(_ error:Error) async {
        guard state.connected else { return }
        state.connected = false; state.detail = "连接中断，正在重连：\(error.localizedDescription)"
        connection?.disconnect(); connection = nil
        if let fault = error as? TransferFault, ["AUTH","CERT","TLS"].contains(fault.code) {
            state.detail = "身份或证书错误：\(fault.message)"; return
        }
        guard let credentials, reconnection == nil else { return }
        let token = generation
        reconnection = Task { [weak self] in
            var delay = 1
            while !Task.isCancelled {
                try? await Task.sleep(for:.seconds(delay))
                guard !Task.isCancelled, let self else { return }
                if await self.tryReconnect(credentials,token:token) { return }
                delay = min(30,delay*2)
            }
        }
    }

    private func tryReconnect(_ credentials:Credentials,token:Int) async -> Bool {
        guard token == generation else { reconnection = nil; return true }
        do {
            try await establish(credentials)
            state.detail = "已重新连接，未完成任务可点击继续"
            reconnection = nil; return true
        } catch {
            state.detail = "重连失败：\(error.localizedDescription)"
            if let fault = error as? TransferFault, ["AUTH","CERT","TLS"].contains(fault.code) { reconnection = nil; return true }
            return false
        }
    }

    public func list(_ path:String) async throws -> [RemoteEntry] {
        _ = try Disk.segments(path,rootAllowed:true)
        var entries:[RemoteEntry] = []; var cursor:Int64 = 0
        repeat {
            let page = try await call(.list,meta:["path":.string(path),"cursor":.integer(cursor)])
            for item in page.meta["entries"]?.values ?? [] {
                let fields = item.fields, name = try item.fields.text("name")
                guard try Disk.segments(name).count == 1 else { throw TransferFault("PROTOCOL","服务器返回无效文件名") }
                entries.append(RemoteEntry(name:name,directory:fields["directory"]?.boolean ?? false,size:try fields.integer("size"),modified:Date(timeIntervalSince1970:fields["modified"]?.double ?? 0)))
            }
            guard entries.count <= 10000 else { throw TransferFault("LIMIT","目录条目超过10000个") }
            if let next = page.meta["next"]?.int {
                guard next > cursor else { throw TransferFault("PROTOCOL","目录分页未取得进展") }; cursor = next
            } else { break }
        } while true
        return entries
    }

    public func mkdir(_ path:String) async throws { _ = try await call(.mkdir,meta:["path":.string(path)]) }

    private func base(root:URL,bookmark:Data?,group:String,title:String,direction:String)->TransferSnapshot {
        var task = TransferSnapshot()
        task.group = group; task.groupName = title; task.owner = state.user; task.endpoint = endpoint
        task.localRoot = root.path; task.bookmark = bookmark; task.direction = direction
        return task
    }

    public func enqueueUploads(root:URL,paths:[String],remoteDirectory:String,bookmark:Data?) async throws -> [String] {
        guard state.connected else { throw TransferFault("DISCONNECTED","请先连接服务器") }
        let manifest = try await disk.run { try Self.localManifest(root:root,paths:paths) }
        let group = UUID().uuidString.lowercased()
        let title = paths.count == 1 ? paths[0] : "\(paths.count)项上传"
        var values:[TransferSnapshot] = []
        for item in manifest.items {
            var task = base(root:root,bookmark:bookmark,group:group,title:title,direction:"upload")
            task.localPath = item.path; task.remotePath = Self.join(remoteDirectory,item.path)
            _ = try Disk.segments(task.remotePath)
            task.directory = item.directory; task.size = item.size; task.created += Double(values.count)/100000
            values.append(task)
        }
        try await store.insert(values)
        await schedule()
        return manifest.warnings
    }

    public func enqueueDownloads(entries:[RemoteEntry],remoteDirectory:String,root:URL,bookmark:Data?) async throws {
        guard state.connected else { throw TransferFault("DISCONNECTED","请先连接服务器") }
        let group = UUID().uuidString.lowercased()
        let title = entries.count == 1 ? entries[0].name : "\(entries.count)项下载"
        var values:[TransferSnapshot] = []
        func append(_ entry:RemoteEntry,local:String,remote:String) throws {
            _ = try Disk.segments(local); _ = try Disk.segments(remote)
            guard values.count < 10000 else { throw TransferFault("LIMIT","文件夹超过10000个条目") }
            var task = base(root:root,bookmark:bookmark,group:group,title:title,direction:"download")
            task.localPath = local; task.remotePath = remote; task.size = entry.directory ? 0 : entry.size; task.directory = entry.directory
            task.created += Double(values.count)/100000; values.append(task)
        }
        var queue:[(RemoteEntry,String,String)] = entries.map { ($0,$0.name,Self.join(remoteDirectory,$0.name)) }
        while !queue.isEmpty {
            let (entry,local,remote) = queue.removeFirst()
            try append(entry,local:local,remote:remote)
            if entry.directory {
                let children = try await list(remote)
                queue.append(contentsOf:children.map { ($0,Self.join(local,$0.name),Self.join(remote,$0.name)) })
            }
        }
        try await store.insert(values); await schedule()
    }

    public func action(_ action:String,ids:Set<String>) async throws {
        for var task in try await store.all() where ids.contains(task.id) {
            guard !["complete","cancelled"].contains(task.status) else { continue }
            if action == "pause" {
                if running[task.id] != nil { controls[task.id] = "pause" }
                else { task.status = "paused"; task.speed = 0; try await store.save(task) }
            } else if action == "cancel" {
                if running[task.id] != nil { controls[task.id] = "cancel" }
                else { task.status = "cancelling"; try await store.save(task) }
            } else if action == "resume" {
                guard running[task.id] == nil else { continue }
                task.status = "queued"; task.detail = ""; try await store.save(task)
            }
        }
        await schedule()
    }

    private func schedule() async {
        guard !scheduling, state.connected, running.count < 4 else { return }
        scheduling = true
        defer { scheduling = false }
        guard let all = try? await store.all() else { return }
        let eligible = all.filter { ["queued","cancelling"].contains($0.status) && $0.owner == state.user && $0.endpoint == endpoint && running[$0.id] == nil }
        let directoryRunning = all.contains { $0.directory && running[$0.id] != nil }
        if let directory = eligible.first(where:{$0.directory}), !directoryRunning {
            launch(directory); return
        }
        for task in eligible where !task.directory {
            if running.count >= 4 { break }
            let dependencies = all.filter { $0.group == task.group && $0.directory && $0.status != "complete" }
            if let failed = dependencies.first(where:{["failed","cancelled"].contains($0.status)}) {
                var blocked = task; blocked.status = "failed"; blocked.detail = "目录任务未完成：\(failed.remotePath)"
                try? await store.save(blocked); continue
            }
            if !dependencies.isEmpty && task.status != "cancelling" { continue }
            launch(task)
        }
    }

    private func launch(_ task:TransferSnapshot) {
        running[task.id] = Task { [weak self] in guard let self else { return }; await self.execute(task) }
    }

    private func execute(_ original:TransferSnapshot) async {
        var task = original
        var scoped:URL?
        defer {
            scoped?.stopAccessingSecurityScopedResource()
            running.removeValue(forKey:task.id); controls.removeValue(forKey:task.id)
            Task { await self.schedule() }
        }
        do {
            var root = URL(fileURLWithPath:task.localRoot,isDirectory:true)
            if let bookmark = task.bookmark {
                var stale = false
                root = try URL(resolvingBookmarkData:bookmark,options:[.withSecurityScope],relativeTo:nil,bookmarkDataIsStale:&stale)
                guard !stale, root.startAccessingSecurityScopedResource() else { throw TransferFault("PERMISSION","本地目录授权已失效，请重新选择目录后重新添加任务") }
                scoped = root
            }
            let localRoot = root
            if task.status == "cancelling" {
                try await cancel(&task,root:root); return
            }
            task.status = "preparing"; task.speed = 0; try await store.save(task)
            if task.directory {
                if task.direction == "upload" { try await mkdir(task.remotePath) }
                else { let path = task.localPath; try await disk.run { try Disk.makeDirectories(root:localRoot,path:path) } }
                task.status = "complete"; try await store.save(task); return
            }
            if task.direction == "upload" { try await upload(&task,root:root) }
            else { try await download(&task,root:root) }
        } catch {
            if error is CancellationError {
                task.status = "waiting"; task.detail = "连接已关闭，可重新连接后继续"
            } else if let fault = error as? TransferFault, ["DISCONNECTED","NETWORK","TIMEOUT"].contains(fault.code) {
                task.status = "waiting"; task.detail = fault.localizedDescription; await lost(error)
            } else {
                task.status = "failed"; task.detail = error.localizedDescription
            }
            task.speed = 0; try? await store.save(task)
        }
    }

    private func upload(_ task:inout TransferSnapshot,root:URL) async throws {
        let path = task.localPath
        let (size,digest) = try await disk.run { try Disk.identity(root:root,path:path) }
        guard task.sha256.isEmpty || (task.sha256 == digest && task.size == size) else { throw TransferFault("CHANGED","源文件已改变，请取消旧任务并重新添加") }
        task.size = size; task.sha256 = digest
        let response:Packet
        if task.started { response = try await call(.resume,meta:["id":.string(task.id)]) }
        else { response = try await call(.put,meta:["id":.string(task.id),"path":.string(task.remotePath),"size":.integer(size),"sha256":.string(digest)]) }
        task.started = true
        if response.kind == .result { task.offset=size; task.status="complete"; try await store.save(task); return }
        let offset = try response.meta.integer("offset")
        guard (0...size).contains(offset), response.meta["sha256"]?.text == digest else { throw TransferFault("INTEGRITY","服务器续传身份不匹配") }
        let (_,prefix) = try await disk.run { try Disk.identity(root:root,path:path,length:offset) }
        guard prefix == response.meta["prefix"]?.text else { throw TransferFault("INTEGRITY","上传续传前缀不匹配，请重新添加任务") }
        task.offset = offset; task.status="transferring"; try await store.save(task)
        let start=Date(); let initial=offset
        while task.offset < size {
            if try await stopIfRequested(&task,root:root) { return }
            let current=task.offset
            let data = try await disk.run { try Disk.read(root:root,path:path,offset:current,length:Int(min(Int64(Packet.chunk),size-current))) }
            guard !data.isEmpty else { throw TransferFault("CHANGED","源文件长度发生变化") }
            let ack = try await call(.data,meta:["id":.string(task.id),"offset":.integer(current)],payload:data)
            guard try ack.meta.integer("offset") == current+Int64(data.count) else { throw TransferFault("PROTOCOL","确认偏移错误") }
            task.offset += Int64(data.count); task.speed=Double(task.offset-initial)/max(0.001,Date().timeIntervalSince(start))
            try await store.save(task)
        }
        if try await stopIfRequested(&task,root:root) { return }
        let result = try await call(.finish,meta:["id":.string(task.id)])
        guard result.kind == .result, result.meta["sha256"]?.text == digest else { throw TransferFault("INTEGRITY","服务端完成结果不匹配") }
        task.status="complete"; task.speed=0; task.detail="SHA-256校验通过"; try await store.save(task)
    }

    private func download(_ task:inout TransferSnapshot,root:URL) async throws {
        let local=task.localPath, temporary=Self.temporary(task)
        let response:Packet
        if !task.started {
            if try await disk.run({ try Disk.exists(root:root,path:local) }) { throw TransferFault("CONFLICT","已有同名文件，请改名后重试") }
            response = try await call(.get,meta:["id":.string(task.id),"path":.string(task.remotePath)])
            task.size = try response.meta.integer("size"); task.sha256 = try response.meta.text("sha256"); task.started=true
            task.offset=0; try await store.save(task)
            _ = try await disk.run { try Disk.prepare(root:root,temporary:temporary,offset:0) }
        } else {
            // A crash after rename but before the local database commit is recoverable.
            let expectedSize=task.size,expectedHash=task.sha256
            if try await disk.run({try Disk.recoverCommitted(root:root,temporary:temporary,destination:local,size:expectedSize,sha256:expectedHash)}) {
                _ = try await call(.finish,meta:["id":.string(task.id),"sha256":.string(task.sha256)])
                task.offset=task.size;task.status="complete";task.detail="已恢复本地原子提交";try await store.save(task);return
            }
            if try await disk.run({ try Disk.exists(root:root,path:local) }),
               !(try await disk.run({ try Disk.exists(root:root,path:temporary) })) {
                let (size,digest) = try await disk.run { try Disk.identity(root:root,path:local) }
                guard size == task.size, digest == task.sha256 else { throw TransferFault("CONFLICT","目标已有其他文件，请改名后重试") }
                _ = try await call(.finish,meta:["id":.string(task.id),"sha256":.string(task.sha256)])
                task.offset=size; task.status="complete"; try await store.save(task); return
            }
            let offset=task.offset
            let prefix = try await disk.run { try Disk.prepare(root:root,temporary:temporary,offset:offset) }
            response = try await call(.resume,meta:["id":.string(task.id),"offset":.integer(offset),"prefix":.string(prefix)])
            guard response.meta["sha256"]?.text == task.sha256 else { throw TransferFault("CHANGED","服务器文件已改变，请重新添加任务") }
        }
        task.status="transferring"; try await store.save(task)
        let start=Date(), initial=task.offset
        while task.offset < task.size {
            if try await stopIfRequested(&task,root:root) { return }
            let offset=task.offset
            let packet = try await call(.read,meta:["id":.string(task.id),"offset":.integer(offset)])
            guard packet.kind == .data, packet.meta["offset"]?.int == offset, !packet.payload.isEmpty,
                  offset+Int64(packet.payload.count) <= task.size else { throw TransferFault("PROTOCOL","下载数据偏移或长度错误") }
            let data=packet.payload
            try await disk.run { try Disk.write(root:root,path:temporary,offset:offset,data:data) }
            task.offset += Int64(data.count); task.speed=Double(task.offset-initial)/max(0.001,Date().timeIntervalSince(start))
            try await store.save(task)
            _ = try await call(.ack,meta:["id":.string(task.id),"offset":.integer(task.offset)])
        }
        if try await stopIfRequested(&task,root:root) { return }
        let (size,digest) = try await disk.run { try Disk.identity(root:root,path:temporary) }
        guard size == task.size, digest == task.sha256 else { throw TransferFault("INTEGRITY","下载文件校验失败") }
        _ = try await call(.finish,meta:["id":.string(task.id),"sha256":.string(digest)])
        try await disk.run { try Disk.commit(root:root,temporary:temporary,destination:local) }
        task.status="complete"; task.speed=0; task.detail="SHA-256校验通过"; try await store.save(task)
    }

    private func stopIfRequested(_ task:inout TransferSnapshot,root:URL) async throws -> Bool {
        try Task.checkCancellation()
        guard let action = controls[task.id] else { return false }
        if action == "cancel" { try await cancel(&task,root:root) }
        else {
            _ = try await call(.pause,meta:["id":.string(task.id)])
            task.status="paused"; task.speed=0; try await store.save(task)
        }
        return true
    }

    private func cancel(_ task:inout TransferSnapshot,root:URL) async throws {
        if task.started { _ = try await call(.cancel,meta:["id":.string(task.id)]) }
        if task.direction == "download" && !task.directory { let temporary=Self.temporary(task); try await disk.run { try Disk.remove(root:root,path:temporary) } }
        task.status="cancelled"; task.speed=0; task.detail="已保留完成文件，清理未完成数据"; try await store.save(task)
    }

    public static func join(_ parent:String,_ name:String)->String { parent.isEmpty ? name : parent+"/"+name }
    private static func temporary(_ task:TransferSnapshot)->String {
        let pieces=task.localPath.components(separatedBy:"/")
        return (Array(pieces.dropLast())+[".sft-\(task.id).part"]).joined(separator:"/")
    }

    private struct ManifestItem: Sendable { var path:String; var directory:Bool; var size:Int64 }
    private struct Manifest: Sendable { var items:[ManifestItem]; var warnings:[String] }
    private static func localManifest(root:URL,paths:[String]) throws -> Manifest {
        var result=Manifest(items:[],warnings:[])
        var pending=paths
        while !pending.isEmpty {
            let path=pending.removeFirst(), pieces=try Disk.segments(path)
            let url=pieces.reduce(root) { $0.appendingPathComponent($1) }
            let info=try url.resourceValues(forKeys:[.isDirectoryKey,.isSymbolicLinkKey,.isRegularFileKey,.fileSizeKey])
            if info.isSymbolicLink == true { result.warnings.append("已跳过符号链接：\(path)"); continue }
            guard info.isDirectory == true || info.isRegularFile == true else { result.warnings.append("已跳过特殊文件：\(path)"); continue }
            guard result.items.count < 10000 else { throw TransferFault("LIMIT","文件夹超过10000个条目") }
            result.items.append(ManifestItem(path:path,directory:info.isDirectory == true,size:Int64(info.fileSize ?? 0)))
            if info.isDirectory == true {
                let children=try FileManager.default.contentsOfDirectory(atPath:url.path).sorted().filter { !$0.hasPrefix(".sft-") }
                pending.append(contentsOf:children.map { join(path,$0) })
            }
        }
        return result
    }
}
