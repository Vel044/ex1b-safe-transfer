import AppKit
import SwiftUI
import SafeTransferCore

struct FileClipboard: Codable {
    static let type = "org.sft1.transfer.files"
    let local:Bool
    let root:String
    let directory:String
    let names:[String]
    let host:String
    let user:String
}

extension AppModel {
    func copyFiles(_ local:Bool, ids:Set<String>? = nil){
        if let ids { if local { localSelection=ids } else { remoteSelection=ids } }
        let value=FileClipboard(local:local,root:root?.path ?? "",directory:local ? localPath : remotePath,names:(local ? localSelection : remoteSelection).sorted(),host:session.connectionID,user:session.user)
        guard !value.names.isEmpty, let data=try? JSONEncoder().encode(value) else{return}
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setData(data,forType:NSPasteboard.PasteboardType(FileClipboard.type))
        notice="已复制所选项目，请在目标文件栏粘贴"
    }
    func pasteFiles(_ local:Bool){
        guard let data=NSPasteboard.general.data(forType:NSPasteboard.PasteboardType(FileClipboard.type)) else{return}
        receiveFiles(data,local:local)
    }
    func receiveFiles(_ data:Data,local destinationLocal:Bool){
        guard let source=try? JSONDecoder().decode(FileClipboard.self,from:data),!source.names.isEmpty else{return}
        let destination=destinationLocal ? localPath : remotePath
        let destinationRoot=root
        guard source.local || (source.host == session.connectionID && source.user == session.user && session.connected) else{errorText="远端来源连接已改变，请重新复制";return}
        guard destinationLocal || (session.connected && session.writable) else{errorText="当前服务器账户没有写入权限";return}
        working=true
        Task{
            defer{working=false}
            do{
                for name in source.names { guard try Disk.segments(name).count == 1 else{throw TransferFault("INPUT","文件名无效")} }
                if source.local && !destinationLocal {
                    guard source.root == destinationRoot?.path,let root=destinationRoot else{throw TransferFault("PERMISSION","本地授权目录已改变，请重新复制")}
                    let from=try localURL(root,source.directory)
                    let bookmark=try from.bookmarkData(options:.withSecurityScope,includingResourceValuesForKeys:nil,relativeTo:nil)
                    _ = try await engine.enqueueUploads(root:from,paths:source.names,remoteDirectory:destination,bookmark:bookmark)
                }else if !source.local && destinationLocal {
                    guard let root=destinationRoot else{throw TransferFault("INPUT","请先选择本地目录")}
                    let to=try localURL(root,destination)
                    let entries=try await engine.list(source.directory).filter{source.names.contains($0.name)}
                    let bookmark=try to.bookmarkData(options:.withSecurityScope,includingResourceValuesForKeys:nil,relativeTo:nil)
                    try await engine.enqueueDownloads(entries:entries,remoteDirectory:source.directory,root:to,bookmark:bookmark)
                }else if source.local {
                    guard source.root == destinationRoot?.path,let root=destinationRoot else{throw TransferFault("PERMISSION","本地授权目录已改变")}
                    let from=try localURL(root,source.directory),to=try localURL(root,destination)
                    for name in source.names {
                        let target=to.appendingPathComponent(name)
                        guard target != from.appendingPathComponent(name),!to.path.hasPrefix(from.appendingPathComponent(name).path+"/") else{throw TransferFault("INPUT","请选择其他目标目录")}
                        try await disk.run{try FileManager.default.copyItem(at:from.appendingPathComponent(name),to:target)}
                    }
                }else{
                    for name in source.names { try await engine.copyFile(TransferEngine.join(source.directory,name),to:TransferEngine.join(destination,name)) }
                }
                notice="所选项目已复制或加入传输队列"
            }catch{errorText=error.localizedDescription}
            await refreshLocal();if session.connected{await refreshRemote()}
        }
    }
    private func localURL(_ root:URL,_ path:String)throws->URL{
        let pieces=try Disk.segments(path,rootAllowed:true)
        return try Disk.withDirectory(root:root,pieces:pieces){_ in pieces.reduce(root){$0.appendingPathComponent($1)}}
    }
    func revealInFinder(currentDirectory:Bool=false){
        guard let root else{return}
        do{
            let directory=try localURL(root,localPath)
            if currentDirectory || localSelection.isEmpty {
                if !NSWorkspace.shared.open(directory){throw TransferFault("IO","无法在 Finder 中打开目录")}
            }else{
                let urls=try localSelection.sorted().map{name -> URL in
                    guard try Disk.segments(name).count == 1 else{throw TransferFault("INPUT","文件名无效")}
                    return directory.appendingPathComponent(name)
                }
                NSWorkspace.shared.activateFileViewerSelecting(urls)
            }
        }catch{errorText=error.localizedDescription}
    }
    func deleteFiles(_ local:Bool,ids:Set<String>? = nil){
        let selected=ids ?? (local ? localSelection : remoteSelection)
        guard !selected.isEmpty else{return}
        let path=local ? localPath : remotePath
        let selectedRoot=root
        guard local || session.writable else{return}
        let alert=NSAlert()
        alert.messageText=local ? "将所选 \(selected.count) 个项目移到废纸篓？" : "永久删除服务器上的 \(selected.count) 个项目？"
        alert.informativeText=local ? "文件夹内的内容也会移到废纸篓。" : "此操作无法撤销，文件夹内容也会删除。正在传输的路径需先完成或取消任务。"
        alert.addButton(withTitle:local ? "移到废纸篓" : "删除");alert.addButton(withTitle:"取消")
        guard alert.runModal() == .alertFirstButtonReturn else{return}
        Task{do{
            for name in selected.sorted(){
                guard try Disk.segments(name).count == 1 else{throw TransferFault("INPUT","文件名无效")}
                if local,let root=selectedRoot{
                    let directory=try localURL(root,path)
                    let url=directory.appendingPathComponent(name)
                    try await disk.run{_ = try FileManager.default.trashItem(at:url,resultingItemURL:nil)}
                }else{try await engine.deleteFile(TransferEngine.join(path,name))}
            }
        }catch{errorText=error.localizedDescription}
            if local{await refreshLocal()}else{await refreshRemote()}
        }
    }
}
