import XCTest
@testable import SafeTransferCore

final class ProtocolTests:XCTestCase {
    func testSplitAndCombinedFrames() throws {
        let original=Packet(.data,request:0x10203040,meta:["name":.string("中文"),"offset":.integer(42)],payload:Data([0,1,255]))
        let bytes=try original.encode()
        XCTAssertEqual(Array(bytes.prefix(12)),[83,70,84,49,1,23,0,0,16,32,48,64])
        var decoder=PacketDecoder(),result:[Packet]=[]
        for byte in bytes { result += try decoder.append(Data([byte])) }
        XCTAssertEqual(result.count,1)
        XCTAssertEqual(result[0].meta,original.meta)
        XCTAssertEqual(result[0].payload,original.payload)
        XCTAssertEqual(try decoder.append(bytes+bytes).count,2)
    }
    func testRejectOversizeAndTraversal() throws {
        var decoder=PacketDecoder()
        let oversize=Data([83,70,84,49,1,40,0,0,0,0,0,1,0,1,0,1,0,0,0,0])
        XCTAssertThrowsError(try decoder.append(oversize))
        for path in ["../secret","/etc/passwd","a//b","a/../b","a\\b"] { XCTAssertThrowsError(try Disk.segments(path)) }
    }
    func testDiskNoOverwriteAndLinks() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:root) }
        _ = try Disk.prepare(root:root,temporary:"part",offset:0)
        try Disk.write(root:root,path:"part",offset:0,data:Data("abc".utf8))
        XCTAssertEqual(try Disk.identity(root:root,path:"part").1,"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        try Data("original".utf8).write(to:root.appendingPathComponent("target"))
        XCTAssertThrowsError(try Disk.commit(root:root,temporary:"part",destination:"target"))
        XCTAssertEqual(try Data(contentsOf:root.appendingPathComponent("target")),Data("original".utf8))
        try FileManager.default.createSymbolicLink(atPath:root.appendingPathComponent("link").path,withDestinationPath:"/etc/passwd")
        XCTAssertThrowsError(try Disk.identity(root:root,path:"link"))
    }
    func testPersistentTaskRecovery() async throws {
        let store=try TaskStore(inMemory:true)
        var task=TransferSnapshot(); task.status="transferring"; task.offset=65536
        try await store.save(task); try await store.recover()
        let recovered=try await store.all()
        XCTAssertEqual(recovered.first?.offset,65536)
        XCTAssertEqual(recovered.first?.status,"paused")
    }
}
