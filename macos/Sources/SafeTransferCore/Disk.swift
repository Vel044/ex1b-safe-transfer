import Foundation
import CryptoKit
import Darwin

public final class DiskWorker: @unchecked Sendable {
    private let queue = DispatchQueue(label:"edu.ucas.ex1b.disk",qos:.utility,attributes:.concurrent)
    private let slots = DispatchSemaphore(value:4)
    public init() {}
    public func run<T:Sendable>(_ operation: @escaping @Sendable () throws -> T) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                self.slots.wait(); defer { self.slots.signal() }
                do { continuation.resume(returning:try operation()) }
                catch { continuation.resume(throwing:error) }
            }
        }
    }
}

public enum Disk {
    public static func segments(_ path: String, rootAllowed: Bool = false) throws -> [String] {
        if path.isEmpty && rootAllowed { return [] }
        let pieces = path.components(separatedBy:"/")
        guard path.utf8.count <= 4096, !path.contains("\0"), !path.contains("\\"), pieces.count <= 32,
              pieces.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && $0.utf8.count <= 255 }) else {
            throw TransferFault("PERMISSION","文件路径无效或越界")
        }
        return pieces
    }

    public static func withDirectory<T>(root:URL, pieces:[String], create:Bool = false, body:(Int32)throws->T) throws -> T {
        var fd = Darwin.open(root.path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW)
        guard fd >= 0 else { throw failure("打开目录") }
        defer { Darwin.close(fd) }
        for piece in pieces {
            if create && mkdirat(fd,piece,0o700) != 0 && errno != EEXIST { throw failure("创建目录") }
            let child = openat(fd,piece,O_RDONLY|O_DIRECTORY|O_NOFOLLOW)
            guard child >= 0 else { throw failure("访问目录") }
            Darwin.close(fd); fd = child
        }
        return try body(fd)
    }

    public static func withFile<T>(root:URL,path:String,body:(Int32)throws->T)throws->T {
        let pieces = try segments(path)
        return try withDirectory(root:root,pieces:Array(pieces.dropLast())) { parent in
            let fd = openat(parent,pieces.last!,O_RDONLY|O_NOFOLLOW|O_NONBLOCK)
            guard fd >= 0 else { throw failure("打开文件") }
            defer { Darwin.close(fd) }
            var info = stat()
            guard fstat(fd,&info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_nlink == 1 else {
                throw TransferFault("PERMISSION","仅允许普通文件，不允许链接或设备")
            }
            return try body(fd)
        }
    }

    public static func hashFD(_ fd:Int32,length:Int64? = nil)throws->String {
        var hasher = SHA256(); var position:Int64 = 0
        var buffer = [UInt8](repeating:0,count:1024*1024)
        while length == nil || position < length! {
            let amount = min(buffer.count,Int((length ?? (position+Int64(buffer.count)))-position))
            let count = pread(fd,&buffer,amount,off_t(position))
            guard count >= 0 else { throw failure("读取文件") }
            if count == 0 { break }
            hasher.update(data:Data(buffer.prefix(count))); position += Int64(count)
        }
        if let length, position != length { throw TransferFault("INTEGRITY","文件长度小于续传检查点") }
        return hasher.finalize().map { String(format:"%02x",$0) }.joined()
    }

    public static func identity(root:URL,path:String,length:Int64? = nil)throws->(Int64,String) {
        try withFile(root:root,path:path) { fd in
            var before = stat(); guard fstat(fd,&before) == 0 else { throw failure("读取属性") }
            let digest = try hashFD(fd,length:length)
            var after = stat(); guard fstat(fd,&after) == 0 else { throw failure("读取属性") }
            guard before.st_size == after.st_size, before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
                  before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec else { throw TransferFault("CHANGED","源文件发生变化") }
            return (Int64(before.st_size),digest)
        }
    }

    public static func read(root:URL,path:String,offset:Int64,length:Int)throws->Data {
        try withFile(root:root,path:path) { fd in
            var buffer = [UInt8](repeating:0,count:length)
            let count = pread(fd,&buffer,length,off_t(offset))
            guard count >= 0 else { throw failure("读取文件") }
            return Data(buffer.prefix(count))
        }
    }

    public static func makeDirectories(root:URL,path:String)throws {
        try withDirectory(root:root,pieces:segments(path,rootAllowed:true),create:true) { _ in }
    }

    public static func exists(root:URL,path:String)throws->Bool {
        let pieces = try segments(path)
        return try withDirectory(root:root,pieces:Array(pieces.dropLast())) { fd in
            var info = stat()
            if fstatat(fd,pieces.last!,&info,AT_SYMLINK_NOFOLLOW) == 0 { return true }
            if errno == ENOENT { return false }
            throw failure("检查目标")
        }
    }

    public static func prepare(root:URL,temporary:String,offset:Int64)throws->String {
        let pieces = try segments(temporary)
        return try withDirectory(root:root,pieces:Array(pieces.dropLast())) { parent in
            let fd = openat(parent,pieces.last!,O_CREAT|O_RDWR|O_NOFOLLOW,0o600)
            guard fd >= 0 else { throw failure("打开临时文件") }
            defer { Darwin.close(fd) }
            var info = stat()
            guard fstat(fd,&info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_nlink == 1,
                  info.st_size >= offset else { throw TransferFault("INTEGRITY","临时文件与检查点不符") }
            guard ftruncate(fd,off_t(offset)) == 0, fsync(fd) == 0 else { throw failure("恢复临时文件") }
            return try hashFD(fd,length:offset)
        }
    }

    public static func write(root:URL,path:String,offset:Int64,data:Data)throws {
        let pieces = try segments(path)
        try withDirectory(root:root,pieces:Array(pieces.dropLast())) { parent in
            let fd = openat(parent,pieces.last!,O_WRONLY|O_NOFOLLOW)
            guard fd >= 0 else { throw failure("打开临时文件") }
            defer { Darwin.close(fd) }
            var info = stat()
            guard fstat(fd,&info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_nlink == 1,
                  info.st_size == offset else { throw TransferFault("INTEGRITY","临时文件偏移错误") }
            try data.withUnsafeBytes { buffer in
                var written = 0
                while written < data.count {
                    let count = pwrite(fd,buffer.baseAddress!.advanced(by:written),data.count-written,off_t(offset)+off_t(written))
                    guard count > 0 else { throw failure("写入临时文件") }; written += count
                }
            }
            guard fsync(fd) == 0 else { throw failure("同步临时文件") }
        }
    }

    public static func commit(root:URL,temporary:String,destination:String)throws {
        let source = try segments(temporary), target = try segments(destination)
        try withDirectory(root:root,pieces:Array(source.dropLast())) { sourceFD in
            try withDirectory(root:root,pieces:Array(target.dropLast())) { targetFD in
                if linkat(sourceFD,source.last!,targetFD,target.last!,0) != 0 {
                    guard errno == EEXIST else { throw failure("提交文件") }
                    var sourceInfo=stat(),targetInfo=stat()
                    guard fstatat(sourceFD,source.last!,&sourceInfo,AT_SYMLINK_NOFOLLOW) == 0,
                          fstatat(targetFD,target.last!,&targetInfo,AT_SYMLINK_NOFOLLOW) == 0,
                          sourceInfo.st_dev == targetInfo.st_dev,sourceInfo.st_ino == targetInfo.st_ino else {
                        throw TransferFault("CONFLICT","已有同名文件，请改名后重试")
                    }
                }
                guard fsync(targetFD) == 0 else { throw failure("同步目录") }
                guard unlinkat(sourceFD,source.last!,0) == 0 else { throw failure("清理临时文件") }
            }
        }
    }

    /// Recover only the exact hard link created by our interrupted commit.
    public static func recoverCommitted(root:URL,temporary:String,destination:String,size:Int64,sha256:String)throws->Bool {
        let source=try segments(temporary),target=try segments(destination)
        return try withDirectory(root:root,pieces:Array(source.dropLast())) { sourceFD in
            try withDirectory(root:root,pieces:Array(target.dropLast())) { targetFD in
                var a=stat(),b=stat()
                if fstatat(sourceFD,source.last!,&a,AT_SYMLINK_NOFOLLOW) != 0 {
                    if errno == ENOENT{return false};throw failure("检查临时文件")
                }
                if fstatat(targetFD,target.last!,&b,AT_SYMLINK_NOFOLLOW) != 0 {
                    if errno == ENOENT{return false};throw failure("检查目标文件")
                }
                guard a.st_dev == b.st_dev,a.st_ino == b.st_ino else{return false}
                guard a.st_mode & S_IFMT == S_IFREG,a.st_nlink == 2,a.st_size == size else{throw TransferFault("INTEGRITY","本地提交恢复状态无效")}
                let fd=openat(sourceFD,source.last!,O_RDONLY|O_NOFOLLOW)
                guard fd >= 0 else{throw failure("检查已提交文件")}
                defer{Darwin.close(fd)}
                guard try hashFD(fd) == sha256 else{throw TransferFault("INTEGRITY","已提交文件哈希不符")}
                guard unlinkat(sourceFD,source.last!,0) == 0,fsync(sourceFD) == 0 else{throw failure("恢复提交")}
                return true
            }
        }
    }

    public static func remove(root:URL,path:String)throws {
        let pieces = try segments(path)
        try withDirectory(root:root,pieces:Array(pieces.dropLast())) { fd in
            if unlinkat(fd,pieces.last!,0) != 0 && errno != ENOENT { throw failure("清理临时文件") }
        }
    }

    private static func failure(_ action:String)->TransferFault {
        let code = errno == EEXIST ? "CONFLICT" : "IO"
        return TransferFault(code,errno == EEXIST ? "已有同名文件，请改名后重试" : "\(action)失败：\(String(cString:strerror(errno)))")
    }
}
