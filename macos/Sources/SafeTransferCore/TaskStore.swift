import Foundation
import SwiftData

public struct TransferSnapshot: Codable, Identifiable, Sendable, Equatable {
    public var id = UUID().uuidString.lowercased()
    public var group = UUID().uuidString.lowercased()
    public var groupName = ""
    public var owner = ""
    public var endpoint = ""
    public var direction = "upload"
    public var directory = false
    public var localRoot = ""
    public var localPath = ""
    public var bookmark: Data?
    public var remotePath = ""
    public var size: Int64 = 0
    public var offset: Int64 = 0
    public var sha256 = ""
    public var started = false
    public var status = "queued"
    public var detail = ""
    public var speed: Double = 0
    public var created = Date().timeIntervalSince1970
    public init() {}
    public var title: String { remotePath.components(separatedBy:"/").last ?? remotePath }
    public var progress: Double { status == "complete" ? 1 : (size > 0 ? Double(offset)/Double(size) : 0) }
    public var statusText: String {
        ["queued":"排队中","preparing":"校验中","transferring":"传输中","paused":"已暂停","waiting":"等待连接","complete":"已完成","failed":"失败","cancelled":"已取消","cancelling":"取消待同步"][status] ?? status
    }
}

@Model
final class PersistedTransfer {
    @Attribute(.unique) var id: String
    var payload: Data
    init(id:String,payload:Data) { self.id=id; self.payload=payload }
}

public actor TaskStore {
    private let container: ModelContainer
    private let context: ModelContext
    public init(inMemory:Bool = false, location:URL? = nil) throws {
        let schema = Schema([PersistedTransfer.self])
        let configuration:ModelConfiguration
        if let location { configuration = ModelConfiguration(schema:schema,url:location) }
        else { configuration = ModelConfiguration(schema:schema,isStoredInMemoryOnly:inMemory) }
        container = try ModelContainer(for:schema,configurations:[configuration])
        context = ModelContext(container)
        context.autosaveEnabled = false
    }
    public func all() throws -> [TransferSnapshot] {
        try context.fetch(FetchDescriptor<PersistedTransfer>()).map { try JSONDecoder().decode(TransferSnapshot.self,from:$0.payload) }.sorted { $0.created < $1.created }
    }
    public func save(_ value:TransferSnapshot) throws {
        let key = value.id
        var descriptor = FetchDescriptor<PersistedTransfer>(predicate:#Predicate { $0.id == key })
        descriptor.fetchLimit = 1
        let payload = try JSONEncoder().encode(value)
        if let existing = try context.fetch(descriptor).first { existing.payload = payload }
        else { context.insert(PersistedTransfer(id:value.id,payload:payload)) }
        try context.save()
    }
    public func insert(_ values:[TransferSnapshot]) throws {
        for value in values { context.insert(PersistedTransfer(id:value.id,payload:try JSONEncoder().encode(value))) }
        try context.save()
    }
    public func remove(_ ids:Set<String>) throws {
        for item in try context.fetch(FetchDescriptor<PersistedTransfer>()) where ids.contains(item.id) { context.delete(item) }
        try context.save()
    }
    public func recover() throws {
        for var value in try all() where ["queued","preparing","transferring","waiting"].contains(value.status) {
            value.status = "paused"; value.detail = "上次运行未完成，可继续传输"; value.speed = 0
            try save(value)
        }
    }
}
