import Foundation

public enum WireValue: Codable, Sendable, Equatable {
    case string(String), integer(Int64), number(Double), bool(Bool), array([WireValue]), object([String: WireValue]), null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Int64.self) { self = .integer(v) }
        else if let v = try? c.decode(Double.self), v.isFinite { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([WireValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: WireValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .integer(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    public var text: String? { if case .string(let v) = self { return v }; return nil }
    public var int: Int64? { if case .integer(let v) = self { return v }; return nil }
    public var boolean: Bool { if case .bool(let v) = self { return v }; return false }
    public var values: [WireValue] { if case .array(let v) = self { return v }; return [] }
    public var fields: [String: WireValue] { if case .object(let v) = self { return v }; return [:] }
    public var double: Double { if case .number(let v) = self { return v }; return Double(int ?? 0) }
}

public enum Message: UInt8, Sendable {
    case hello = 1, welcome = 2, list = 10, listResult = 11, mkdir = 12, ok = 13
    case delete = 14, copy = 15
    case put = 20, get = 21, ready = 22, data = 23, ack = 24, finish = 25, result = 26, read = 27
    case pause = 30, resume = 31, cancel = 32, ping = 40, pong = 41, error = 255
}

public struct TransferFault: Error, LocalizedError, Sendable {
    public let code: String
    public let message: String
    public init(_ code: String, _ message: String) { self.code = code; self.message = message }
    public var errorDescription: String? { "\(message) [\(code)]" }
}

public struct Packet: Sendable {
    public static let chunk = 65536
    public let kind: Message
    public let request: UInt32
    public let meta: [String: WireValue]
    public let payload: Data
    public init(_ kind: Message, request: UInt32 = 0, meta: [String: WireValue] = [:], payload: Data = Data()) {
        self.kind = kind; self.request = request; self.meta = meta; self.payload = payload
    }
    public func encode() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        let json = try encoder.encode(meta)
        guard json.count <= Self.chunk, payload.count <= Self.chunk else { throw TransferFault("PROTOCOL", "报文超过长度上限") }
        var bytes = Data("SFT1".utf8)
        bytes.append(contentsOf: [1, kind.rawValue, 0, 0])
        for number in [request, UInt32(json.count), UInt32(payload.count)] {
            bytes.append(contentsOf: [UInt8((number >> 24) & 255), UInt8((number >> 16) & 255), UInt8((number >> 8) & 255), UInt8(number & 255)])
        }
        bytes.append(json); bytes.append(payload)
        return bytes
    }
}

public struct PacketDecoder: Sendable {
    private var buffer = Data()
    public init() {}
    public var hasPartial: Bool { !buffer.isEmpty }
    public mutating func append(_ data: Data) throws -> [Packet] {
        guard buffer.count + data.count <= 4 * Packet.chunk + 40 else { throw TransferFault("PROTOCOL", "接收缓冲区超限") }
        buffer.append(data)
        var packets: [Packet] = []
        while buffer.count >= 20 {
            let bytes = [UInt8](buffer.prefix(20))
            guard Array(bytes[0..<4]) == Array("SFT1".utf8), bytes[4] == 1, bytes[6] == 0, bytes[7] == 0, let kind = Message(rawValue: bytes[5]) else {
                throw TransferFault("PROTOCOL", "无效报头")
            }
            func number(_ start: Int) -> UInt32 { bytes[start..<start+4].reduce(0) { ($0 << 8) | UInt32($1) } }
            let request = number(8), mlen = Int(number(12)), dlen = Int(number(16))
            guard mlen <= Packet.chunk, dlen <= Packet.chunk else { throw TransferFault("PROTOCOL", "报文长度超限") }
            let total = 20 + mlen + dlen
            guard buffer.count >= total else { break }
            let raw = Data(buffer.dropFirst(20).prefix(mlen))
            let meta = try JSONDecoder().decode([String: WireValue].self, from: raw)
            packets.append(Packet(kind, request: request, meta: meta, payload: Data(buffer.dropFirst(20+mlen).prefix(dlen))))
            buffer = Data(buffer.dropFirst(total))
        }
        return packets
    }
}

public extension Dictionary where Key == String, Value == WireValue {
    func text(_ key: String) throws -> String {
        guard let value = self[key]?.text else { throw TransferFault("PROTOCOL", "缺少字段 \(key)") }; return value
    }
    func integer(_ key: String) throws -> Int64 {
        guard let value = self[key]?.int else { throw TransferFault("PROTOCOL", "缺少字段 \(key)") }; return value
    }
}
