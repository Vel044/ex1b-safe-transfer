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
            let workspace=URL(fileURLWithPath:option("--root",NSTemporaryDirectory()+"sft-probe-"+UUID().uuidString)).resolvingSymlinksInPath()
            try FileManager.default.createDirectory(at:workspace,withIntermediateDirectories:true)
            let source=workspace.appendingPathComponent("source"),destination=workspace.appendingPathComponent("destination")
            for path in [source,destination] { try FileManager.default.createDirectory(at:path,withIntermediateDirectories:true) }
            let folder="Swift验证-"+UUID().uuidString.prefix(8)
            let directory=source.appendingPathComponent(String(folder))
            try FileManager.default.createDirectory(at:directory.appendingPathComponent("空目录"),withIntermediateDirectories:true)
            let data=Data((0..<300000).map { UInt8($0 % 251) })
            try data.write(to:directory.appendingPathComponent("中文文件.bin"))
            try Data().write(to:directory.appendingPathComponent("empty.txt"))
            try FileManager.default.createSymbolicLink(atPath:directory.appendingPathComponent("不跟随链接").path,withDestinationPath:"/etc/passwd")
            let store=try TaskStore(inMemory:true)
            let engine=TransferEngine(store:store)
            try await engine.initialize()
            try await engine.connect(Credentials(host:option("--host","localhost"),port:port,ca:certs.appendingPathComponent("ca.pem"),identity:certs.appendingPathComponent(user+".p12"),password:try String(contentsOf:certs.appendingPathComponent(user+".password"),encoding:.utf8).trimmingCharacters(in:.whitespacesAndNewlines)))
            let warnings=try await engine.enqueueUploads(root:source,paths:[String(folder)],remoteDirectory:"",bookmark:nil)
            try await awaitCompletion(engine)
            let entries=try await engine.list("").filter { $0.name == folder }
            try await engine.enqueueDownloads(entries:entries,remoteDirectory:"",root:destination,bookmark:nil)
            try await awaitCompletion(engine)
            let (size,digest)=try Disk.identity(root:destination,path:String(folder)+"/中文文件.bin")
            let (_,expected)=try Disk.identity(root:source,path:String(folder)+"/中文文件.bin")
            guard digest == expected,size == data.count,FileManager.default.fileExists(atPath:destination.appendingPathComponent(String(folder)+"/空目录").path) else { throw TransferFault("TEST","文件夹往返不一致") }
            let session=await engine.session()
            let tasks=try await engine.tasks()
            await engine.disconnect()
            let evidence:[String:Any] = ["result":"passed","client":"Swift Network.framework","user":session.user,"files_and_directories":tasks.count,"bytes":size,"sha256":digest,"symlink_warnings":warnings,"workspace":workspace.path]
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
}
