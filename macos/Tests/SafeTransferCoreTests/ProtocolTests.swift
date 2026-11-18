import XCTest
import Darwin
@testable import SafeTransferCore

final class ProtocolTests:XCTestCase {
    func testRecoverCommitBeforeTemporaryUnlink()throws{
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        defer{try? FileManager.default.removeItem(at:root)}
        _ = try Disk.prepare(root:root,temporary:"part",offset:0)
        try Disk.write(root:root,path:"part",offset:0,data:Data("abc".utf8))
        try FileManager.default.linkItem(at:root.appendingPathComponent("part"),to:root.appendingPathComponent("final"))
        let hash="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        XCTAssertTrue(try Disk.recoverCommitted(root:root,temporary:"part",destination:"final",size:3,sha256:hash))
        XCTAssertFalse(try Disk.exists(root:root,path:"part"))
        XCTAssertEqual(try Disk.identity(root:root,path:"final").1,hash)
    }
    func testSharedPythonFixtures() throws {
        struct Fixture:Decodable { var kind:UInt8;var request:UInt32;var meta:[String:WireValue];var payload_hex:String;var wire_hex:String }
        let root=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let fixtures=try JSONDecoder().decode([Fixture].self,from:Data(contentsOf:root.appendingPathComponent("fixtures/protocol.json")))
        func hex(_ string:String)->Data { var data=Data();var i=string.startIndex;while i<string.endIndex{let end=string.index(i,offsetBy:2);data.append(UInt8(string[i..<end],radix:16)!);i=end};return data }
        for fixture in fixtures {
            var decoder=PacketDecoder()
            let packet=try XCTUnwrap(decoder.append(hex(fixture.wire_hex)).first)
            XCTAssertEqual(packet.kind.rawValue,fixture.kind);XCTAssertEqual(packet.request,fixture.request)
            XCTAssertEqual(packet.meta,fixture.meta);XCTAssertEqual(packet.payload,hex(fixture.payload_hex))
        }
    }
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
    func testPublishedDownloadClearsHiddenFlag() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        defer{try? FileManager.default.removeItem(at:root)}
        let temporary=".sft-test.part"
        _ = try Disk.prepare(root:root,temporary:temporary,offset:0)
        try Disk.write(root:root,path:temporary,offset:0,data:Data("visible download".utf8))
        let before=try Disk.identity(root:root,path:temporary)
        XCTAssertEqual(chflags(root.appendingPathComponent(temporary).path,UInt32(UF_HIDDEN)),0)
        try Disk.commit(root:root,temporary:temporary,destination:"中文文件.bin")
        let after=try Disk.identity(root:root,path:"中文文件.bin")
        XCTAssertEqual(before.0,after.0);XCTAssertEqual(before.1,after.1)
        var info=stat()
        XCTAssertEqual(lstat(root.appendingPathComponent("中文文件.bin").path,&info),0)
        XCTAssertEqual(info.st_flags & UInt32(UF_HIDDEN),0)
        XCTAssertFalse(try Disk.exists(root:root,path:temporary))
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
