import Foundation
import SafeTransferCore

@main
struct Probe {
    static func main() async {
        do {
            let args=CommandLine.arguments
            func option(_ flag:String,_ fallback:String)->String { guard let i=args.firstIndex(of:flag),i+1<args.count else { return fallback }; return args[i+1] }
            let certs=URL(fileURLWithPath:option("--certs","runtime/certs")).standardizedFileURL
            let user=option("--user","alice"),port=UInt16(option("--port","8443"))!
            let credentials=Credentials(host:option("--host","localhost"),port:port,ca:certs.appendingPathComponent("ca.pem"),identity:certs.appendingPathComponent(user+".p12"),password:try String(contentsOf:certs.appendingPathComponent(user+".password"),encoding:.utf8).trimmingCharacters(in:.whitespacesAndNewlines))
            if args.contains("--resume-stage") {
                try await resumeStage(option("--resume-stage","start"),state:URL(fileURLWithPath:option("--state","runtime/resume-proof")),credentials:credentials)
                return
            }
            let workspace=URL(fileURLWithPath:option("--root",NSTemporaryDirectory()+"sft-probe-"+UUID().uuidString)).resolvingSymlinksInPath()
            try FileManager.default.createDirectory(at:workspace,withIntermediateDirectories:true)
            let source=workspace.appendingPathComponent("source"),destination=workspace.appendingPathComponent("destination")
            for path in [source,destination] { try FileManager.default.createDirectory(at:path,withIntermediateDirectories:true) }
            let folder="Swift验证-"+UUID().uuidString.prefix(8)
            let directory=source.appendingPathComponent(String(folder))
            try FileManager.default.createDirectory(at:directory.appendingPathComponent("空目录"),withIntermediateDirectories:true)
            let data=Data((0..<300000).map { UInt8($0 % 251) })
            try data.write(to:directory.appendingPathComponent("中文文件.bin"))
            try data.write(to:directory.appendingPathComponent("并发文件A.bin"))
            try data.write(to:directory.appendingPathComponent("并发文件B.bin"))
            try Data().write(to:directory.appendingPathComponent("empty.txt"))
            try FileManager.default.createSymbolicLink(atPath:directory.appendingPathComponent("不跟随链接").path,withDestinationPath:"/etc/passwd")
            let store=try TaskStore(inMemory:true)
            let engine=TransferEngine(store:store)
            try await engine.initialize()
            try await engine.connect(credentials)
            let warnings=try await engine.enqueueUploads(root:source,paths:[String(folder)],remoteDirectory:"",bookmark:nil)
            try await awaitCompletion(engine)
            let entries=try await engine.list("").filter { $0.name == folder }
            try await engine.enqueueDownloads(entries:entries,remoteDirectory:"",root:destination,bookmark:nil)
            try await awaitCompletion(engine)
            let (size,digest)=try Disk.identity(root:destination,path:String(folder)+"/中文文件.bin")
            let (_,expected)=try Disk.identity(root:source,path:String(folder)+"/中文文件.bin")
            guard digest == expected,size == data.count,FileManager.default.fileExists(atPath:destination.appendingPathComponent(String(folder)+"/空目录").path) else { throw TransferFault("TEST","文件夹往返不一致") }
            if let seconds=Double(option("--idle-seconds","0")),seconds > 0 { try await Task.sleep(for:.seconds(seconds)) }
            let session=await engine.session()
            let tasks=try await engine.tasks()
            await engine.disconnect()
            let evidence:[String:Any] = ["result":"passed","client":"Swift Network.framework","user":session.user,"files_and_directories":tasks.count,"bytes":size,"sha256":digest,"symlink_warnings":warnings,"workspace":workspace.path,"heartbeats":session.heartbeats,"connection_id":session.connectionID]
            print(String(data:try JSONSerialization.data(withJSONObject:evidence,options:[.prettyPrinted,.sortedKeys]),encoding:.utf8)!)
        } catch {
            fputs("Swift验证失败：\(error.localizedDescription)\n",stderr)
            exit(1)
        }
    }

    static func awaitCompletion(_ engine:TransferEngine) async throws {
        for _ in 0..<600 {
            let tasks=try await engine.tasks()
            if let failed=tasks.first(where:{["failed","waiting"].contains($0.status)}) { throw TransferFault("TEST",failed.remotePath+"："+failed.detail) }
            if !tasks.isEmpty && tasks.allSatisfy({$0.status == "complete"}) { return }
            try await Task.sleep(for:.milliseconds(100))
        }
        throw TransferFault("TEST","任务完成超时")
    }

    static func resumeStage(_ stage:String,state:URL,credentials:Credentials) async throws {
        let root=state.standardizedFileURL.resolvingSymlinksInPath()
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        let store=try TaskStore(location:root.appendingPathComponent("tasks.sqlite"))
        let engine=TransferEngine(store:store)
        try await engine.initialize();try await engine.connect(credentials)
        if stage == "start" {
            let name="续传验证-"+UUID().uuidString.prefix(8)+".bin"
            try Data(repeating:137,count:4*1024*1024).write(to:root.appendingPathComponent(String(name)))
            _ = try await engine.enqueueUploads(root:root,paths:[String(name)],remoteDirectory:"",bookmark:nil)
            var checkpoint:Int64=0
            for _ in 0..<600 {
                if let task=try await engine.tasks().first,task.offset >= 65536 && task.status == "transferring" {
                    try await engine.action("pause",ids:[task.id]);break
                }
                try await Task.sleep(for:.milliseconds(10))
            }
            for _ in 0..<600 {
                if let task=try await engine.tasks().first,task.status == "paused" {checkpoint=task.offset;break}
                try await Task.sleep(for:.milliseconds(10))
            }
            guard checkpoint > 0,checkpoint < 4*1024*1024 else{throw TransferFault("TEST","未能保存有效续传检查点")}
            await engine.disconnect()
            print("{\"stage\":\"paused\",\"durable_offset\":\(checkpoint)}")
        }else{
            let tasks=try await engine.tasks()
            guard let saved=tasks.first,saved.offset > 0,saved.status == "paused" else{throw TransferFault("TEST","重启后未恢复检查点")}
            try await engine.action("resume",ids:Set(tasks.map(\.id)))
            try await awaitCompletion(engine)
            await engine.disconnect()
            print("{\"stage\":\"resumed_after_process_restart\",\"resumed_from\":\(saved.offset),\"size\":\(saved.size)}")
        }
    }
}
