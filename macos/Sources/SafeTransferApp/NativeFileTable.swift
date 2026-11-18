import AppKit
import SwiftUI

/// AppKit owns row selection, native drag sessions, drop feedback and keyboard focus.
struct NativeFileTable: NSViewRepresentable {
    @ObservedObject var model:AppModel
    let local:Bool

    func makeCoordinator()->Coordinator { Coordinator(self) }
    func makeNSView(context:Context)->NSScrollView {
        let scroll=NSScrollView()
        let table=FileListTable()
        table.allowsMultipleSelection=true
        table.usesAlternatingRowBackgroundColors=true
        table.columnAutoresizingStyle = .lastColumnOnlyAutoresizingStyle
        table.rowHeight=25
        for (key,title,width) in [("name","名称",240.0),("size","大小",85.0),("modified","修改时间",130.0)] {
            let column=NSTableColumn(identifier:NSUserInterfaceItemIdentifier(key))
            column.title=title;column.width=width;column.minWidth=key == "name" ? 140 : 65
            column.sortDescriptorPrototype=NSSortDescriptor(key:key,ascending:true)
            table.addTableColumn(column)
        }
        table.delegate=context.coordinator;table.dataSource=context.coordinator
        table.registerForDraggedTypes([NSPasteboard.PasteboardType(FileClipboard.type)])
        table.setDraggingSourceOperationMask(.copy,forLocal:true)
        table.setDraggingSourceOperationMask([],forLocal:false)
        table.target=context.coordinator;table.doubleAction=#selector(Coordinator.openDirectory)
        table.copyAction={model.copyFiles(local)}
        table.pasteAction={model.pasteFiles(local)}
        table.deleteAction={model.deleteFiles(local)}
        table.transferAction={model.transfer(upload:local)}
        table.revealAction={model.revealInFinder()}
        table.canOpen={
            let ids=local ? model.localSelection : model.remoteSelection
            return ids.count == 1 && (local ? model.local : model.remote).contains{$0.directory && ids.contains($0.name)}
        }
        table.openAction={model.open(local ? model.localSelection : model.remoteSelection,localSide:local)}
        table.canWrite={local || (model.session.connected && model.session.writable)}
        table.canTransfer={model.session.connected && model.root != nil && (!local || model.session.writable)}
        table.localSide=local
        let menu=NSMenu()
        for (title,selector) in [("打开目录",#selector(FileListTable.openSelected(_:))),("复制",#selector(FileListTable.copy(_:))),("粘贴",#selector(FileListTable.paste(_:))),(local ? "移到废纸篓…" : "删除…",#selector(FileListTable.deleteSelected(_:))),(local ? "上传所选项目" : "下载所选项目",#selector(FileListTable.transferSelected(_:)))] {
            let item=NSMenuItem(title:title,action:selector,keyEquivalent:"");item.target=table;menu.addItem(item)
        }
        if local {
            let item=NSMenuItem(title:"在 Finder 中显示",action:#selector(FileListTable.revealSelected(_:)),keyEquivalent:"")
            item.target=table;menu.insertItem(item,at:1)
        }
        table.menu=menu
        scroll.documentView=table;scroll.hasVerticalScroller=true;scroll.hasHorizontalScroller=true
        context.coordinator.table=table
        return scroll
    }
    func updateNSView(_ scroll:NSScrollView,context:Context){
        let c=context.coordinator;c.parent=self
        guard let table=c.table else{return}
        let rows=c.sorted(local ? model.local : model.remote)
        c.updating=true
        defer{c.updating=false}
        if rows != c.rows { c.rows=rows;table.reloadData() }
        let names=local ? model.localSelection : model.remoteSelection
        let indexes=IndexSet(c.rows.indices.filter{names.contains(c.rows[$0].name)})
        if indexes != table.selectedRowIndexes {table.selectRowIndexes(indexes,byExtendingSelection:false)}
    }
    @MainActor final class Coordinator:NSObject,NSTableViewDelegate,NSTableViewDataSource {
        var parent:NativeFileTable
        weak var table:FileListTable?
        var rows:[FileRow]=[]
        var updating=false
        init(_ parent:NativeFileTable){self.parent=parent}
        func sorted(_ values:[FileRow])->[FileRow]{
            guard let descriptor=table?.sortDescriptors.first,let key=descriptor.key else{return values}
            return values.sorted{a,b in
                let order:ComparisonResult
                if key == "size" {order=NSNumber(value:a.size).compare(NSNumber(value:b.size))}
                else if key == "modified" {order=a.modified.compare(b.modified)}
                else {order=a.name.localizedStandardCompare(b.name)}
                return descriptor.ascending ? order == .orderedAscending : order == .orderedDescending
            }
        }
        func numberOfRows(in tableView:NSTableView)->Int{rows.count}
        func tableView(_ tableView:NSTableView,viewFor column:NSTableColumn?,row:Int)->NSView?{
            guard rows.indices.contains(row),let key=column?.identifier.rawValue else{return nil}
            let row=rows[row]
            let cell=NSTableCellView()
            let label=NSTextField(labelWithString:key == "name" ? row.name : key == "size" ? row.sizeText : DateFormatter.localizedString(from:row.modified,dateStyle:.short,timeStyle:.short))
            label.lineBreakMode = .byTruncatingMiddle
            label.textColor=key == "name" ? .labelColor : .secondaryLabelColor
            label.translatesAutoresizingMaskIntoConstraints=false;cell.addSubview(label);cell.textField=label
            if key == "name" {
                let image=NSImageView(image:NSImage(systemSymbolName:row.directory ? "folder.fill" : "doc",accessibilityDescription:row.directory ? "文件夹" : "文件") ?? NSImage())
                image.contentTintColor=row.directory ? .controlAccentColor : .secondaryLabelColor
                image.translatesAutoresizingMaskIntoConstraints=false;cell.addSubview(image);cell.imageView=image
                NSLayoutConstraint.activate([image.leadingAnchor.constraint(equalTo:cell.leadingAnchor,constant:5),image.widthAnchor.constraint(equalToConstant:18),image.centerYAnchor.constraint(equalTo:cell.centerYAnchor),label.leadingAnchor.constraint(equalTo:image.trailingAnchor,constant:6)])
            }else{label.leadingAnchor.constraint(equalTo:cell.leadingAnchor,constant:5).isActive=true}
            NSLayoutConstraint.activate([label.trailingAnchor.constraint(equalTo:cell.trailingAnchor,constant:-5),label.centerYAnchor.constraint(equalTo:cell.centerYAnchor)])
            return cell
        }
        func tableViewSelectionDidChange(_ notification:Notification){
            guard !updating,let table else{return}
            let selected=Set(table.selectedRowIndexes.compactMap{rows.indices.contains($0) ? rows[$0].name : nil})
            if parent.local {parent.model.localSelection=selected}else{parent.model.remoteSelection=selected}
        }
        func tableView(_ tableView:NSTableView,sortDescriptorsDidChange oldDescriptors:[NSSortDescriptor]){
            rows=sorted(rows);tableView.reloadData()
            let selected=parent.local ? parent.model.localSelection : parent.model.remoteSelection
            updating=true;tableView.selectRowIndexes(IndexSet(rows.indices.filter{selected.contains(rows[$0].name)}),byExtendingSelection:false);updating=false
        }
        @objc func openDirectory(){parent.model.open(parent.local ? parent.model.localSelection : parent.model.remoteSelection,localSide:parent.local)}
        func tableView(_ tableView:NSTableView,pasteboardWriterForRow row:Int)->NSPasteboardWriting?{
            guard rows.indices.contains(row),!parent.model.working else{return nil}
            let model=parent.model
            let value=FileClipboard(local:parent.local,root:model.root?.path ?? "",directory:parent.local ? model.localPath : model.remotePath,names:[rows[row].name],host:model.session.connectionID,user:model.session.user)
            guard let data=try? JSONEncoder().encode(value) else{return nil}
            let item=NSPasteboardItem();item.setData(data,forType:NSPasteboard.PasteboardType(FileClipboard.type));return item
        }
        func payload(_ pasteboard:NSPasteboard)->FileClipboard?{
            let values=(pasteboard.pasteboardItems ?? []).compactMap{item->FileClipboard? in
                guard let data=item.data(forType:NSPasteboard.PasteboardType(FileClipboard.type)) else{return nil}
                return try? JSONDecoder().decode(FileClipboard.self,from:data)
            }
            guard let first=values.first,values.allSatisfy({$0.local == first.local && $0.root == first.root && $0.directory == first.directory && $0.host == first.host && $0.user == first.user}) else{return nil}
            return FileClipboard(local:first.local,root:first.root,directory:first.directory,names:Array(Set(values.flatMap(\.names))).sorted(),host:first.host,user:first.user)
        }
        func tableView(_ tableView:NSTableView,validateDrop info:NSDraggingInfo,proposedRow row:Int,proposedDropOperation operation:NSTableView.DropOperation)->NSDragOperation{
            let model=parent.model
            guard !model.working,model.root != nil,model.session.connected,
                  parent.local || model.session.writable,let source=payload(info.draggingPasteboard),source.local != parent.local,
                  source.local || (source.host == model.session.connectionID && source.user == model.session.user) else{return []}
            tableView.setDropRow(-1,dropOperation:.on)
            return .copy
        }
        func tableView(_ tableView:NSTableView,acceptDrop info:NSDraggingInfo,row:Int,dropOperation:NSTableView.DropOperation)->Bool{
            guard self.tableView(tableView,validateDrop:info,proposedRow:row,proposedDropOperation:dropOperation) == .copy,
                  let source=payload(info.draggingPasteboard),let data=try? JSONEncoder().encode(source) else{return false}
            parent.model.receiveFiles(data,local:parent.local);return true
        }
    }
}

@MainActor final class FileListTable:NSTableView,NSMenuItemValidation {
    var copyAction:(()->Void)?
    var pasteAction:(()->Void)?
    var deleteAction:(()->Void)?
    var transferAction:(()->Void)?
    var openAction:(()->Void)?
    var revealAction:(()->Void)?
    var canOpen:(()->Bool)?
    var canWrite:(()->Bool)?
    var canTransfer:(()->Bool)?
    var localSide=false
    @objc func copy(_ sender:Any?){copyAction?()}
    @objc func paste(_ sender:Any?){pasteAction?()}
    @objc func deleteSelected(_ sender:Any?){if canWrite?() == true{deleteAction?()}}
    @objc func transferSelected(_ sender:Any?){transferAction?()}
    @objc func openSelected(_ sender:Any?){if canOpen?() == true{openAction?()}}
    @objc func revealSelected(_ sender:Any?){revealAction?()}
    override func keyDown(with event:NSEvent){
        let flags=event.modifierFlags.intersection([.command,.option,.control,.shift])
        if flags == .command {
            if event.keyCode == 51 {if numberOfSelectedRows > 0{deleteSelected(nil)};return}
            if event.charactersIgnoringModifiers == "c" {copy(nil);return}
            if event.charactersIgnoringModifiers == "v" {if canWrite?() == true{paste(nil)};return}
        }
        super.keyDown(with:event)
    }
    override func menu(for event:NSEvent)->NSMenu?{
        let row=row(at:convert(event.locationInWindow,from:nil))
        if row >= 0 && !selectedRowIndexes.contains(row){selectRowIndexes(IndexSet(integer:row),byExtendingSelection:false)}
        if row < 0 {deselectAll(nil)}
        for item in menu?.items ?? [] where item.action == #selector(openSelected(_:)) {
            item.isHidden=canOpen?() != true
        }
        window?.makeFirstResponder(self)
        return super.menu(for:event)
    }
    func validateMenuItem(_ item:NSMenuItem)->Bool{
        switch item.action {
        case #selector(copy(_:)):return numberOfSelectedRows > 0
        case #selector(paste(_:)):return canWrite?() == true && NSPasteboard.general.data(forType:NSPasteboard.PasteboardType(FileClipboard.type)) != nil
        case #selector(deleteSelected(_:)):return numberOfSelectedRows > 0 && canWrite?() == true
        case #selector(transferSelected(_:)):return numberOfSelectedRows > 0 && canTransfer?() == true
        case #selector(openSelected(_:)):return canOpen?() == true
        case #selector(revealSelected(_:)):return localSide
        default:return true
        }
    }
}
