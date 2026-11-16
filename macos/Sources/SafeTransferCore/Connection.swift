import Foundation
import Network
import Security

public struct Credentials: Sendable {
    public var host: String
    public var port: UInt16
    public var ca: URL
    public var identity: URL
    public var password: String
    public init(host: String, port: UInt16, ca: URL, identity: URL, password: String) {
        self.host = host; self.port = port; self.ca = ca; self.identity = identity; self.password = password
    }
}

/// All mutable transport state is confined to queue. The protocol is a byte stream.
public final class SecureConnection: @unchecked Sendable {
    private let queue = DispatchQueue(label: "edu.ucas.ex1b.connection")
    private var connection: NWConnection?
    private var decoder = PacketDecoder()
    private var pending: [UInt32: CheckedContinuation<Packet, Error>] = [:]
    private var nextID: UInt32 = 0
    private var ready: CheckedContinuation<Void, Error>?
    private var partialSince: Date?
    private var watchdog: DispatchSourceTimer?
    private var closed = true

    public init() {}

    public func connect(_ credentials: Credentials) async throws -> Packet {
        let options = try Self.parameters(credentials)
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                self.closed = false
                self.ready = continuation
                self.decoder = PacketDecoder()
                let connection = NWConnection(host: NWEndpoint.Host(credentials.host), port: NWEndpoint.Port(rawValue: credentials.port)!, using: options)
                self.connection = connection
                connection.stateUpdateHandler = { state in
                    switch state {
                    case .ready:
                        self.ready?.resume(); self.ready = nil
                        self.receive()
                    case .failed(let error):
                        if case .tls = error { self.fail(TransferFault("TLS",error.localizedDescription)) }
                        else { self.fail(TransferFault("NETWORK",error.localizedDescription)) }
                    case .cancelled: self.fail(TransferFault("DISCONNECTED","连接已关闭"))
                    default: break
                    }
                }
                connection.start(queue: self.queue)
                self.queue.asyncAfter(deadline: .now()+10) {
                    if self.ready != nil { self.fail(TransferFault("TIMEOUT","连接或证书验证超时")) }
                }
                let timer = DispatchSource.makeTimerSource(queue: self.queue)
                timer.schedule(deadline: .now()+1,repeating: 1)
                timer.setEventHandler {
                    if let start = self.partialSince, Date().timeIntervalSince(start) > 15 {
                        self.fail(TransferFault("TIMEOUT","接收不完整报文超时"))
                    }
                }
                self.watchdog = timer; timer.resume()
            }
        }
        return try await request(.hello, meta: ["version":.integer(1)])
    }

    public func request(_ kind: Message, meta: [String: WireValue] = [:], payload: Data = Data(), timeout: TimeInterval = 60) async throws -> Packet {
        try Task.checkCancellation()
        return try await withCheckedThrowingContinuation { continuation in
            queue.async {
                guard !self.closed, let connection = self.connection else {
                    continuation.resume(throwing: TransferFault("DISCONNECTED","尚未连接服务器")); return
                }
                guard self.pending.count < 16 else {
                    continuation.resume(throwing: TransferFault("LIMIT","并发请求超过上限")); return
                }
                repeat { self.nextID &+= 1 } while self.nextID == 0 || self.pending[self.nextID] != nil
                let id = self.nextID
                do {
                    let bytes = try Packet(kind,request:id,meta:meta,payload:payload).encode()
                    self.pending[id] = continuation
                    connection.send(content:bytes,completion:.contentProcessed { error in
                        if let error { self.fail(TransferFault("NETWORK",error.localizedDescription)) }
                    })
                    self.queue.asyncAfter(deadline:.now()+timeout) {
                        if self.pending[id] != nil { self.fail(TransferFault("TIMEOUT","服务器响应超时")) }
                    }
                } catch { continuation.resume(throwing:error) }
            }
        }
    }

    public func disconnect() {
        queue.async { self.fail(TransferFault("DISCONNECTED","连接已断开")) }
    }

    private func receive() {
        guard !closed else { return }
        connection?.receive(minimumIncompleteLength:1,maximumLength:65536) { data,_,complete,error in
            do {
                if let data, !data.isEmpty {
                    let packets = try self.decoder.append(data)
                    for packet in packets {
                        if packet.kind == .error {
                            let fault = TransferFault(packet.meta["code"]?.text ?? "SERVER",packet.meta["message"]?.text ?? "服务器拒绝操作")
                            if packet.request == 0 { self.fail(fault); return }
                            self.pending.removeValue(forKey:packet.request)?.resume(throwing:fault)
                        } else {
                            guard let continuation = self.pending.removeValue(forKey:packet.request) else {
                                throw TransferFault("PROTOCOL","收到未知请求的响应")
                            }
                            continuation.resume(returning:packet)
                        }
                    }
                    if self.decoder.hasPartial {
                        if self.partialSince == nil || !packets.isEmpty { self.partialSince = Date() }
                    } else { self.partialSince = nil }
                }
                        if let error { self.fail(TransferFault("NETWORK",error.localizedDescription)) }
                else if complete { self.fail(TransferFault("DISCONNECTED","服务器关闭了连接")) }
                else { self.receive() }
            } catch { self.fail(error) }
        }
    }

    private func fail(_ error: Error) {
        guard !closed else { return }
        closed = true
        watchdog?.cancel(); watchdog = nil
        connection?.cancel(); connection = nil
        ready?.resume(throwing:error); ready = nil
        let waiting = pending.values
        pending.removeAll()
        for continuation in waiting { continuation.resume(throwing:error) }
    }

    private static func parameters(_ credentials: Credentials) throws -> NWParameters {
        let caData = try Data(contentsOf:credentials.ca)
        let der: Data
        if let pem = String(data:caData,encoding:.utf8), pem.contains("BEGIN CERTIFICATE") {
            let base64 = pem.components(separatedBy:.newlines).filter { !$0.hasPrefix("---") }.joined()
            guard let decoded = Data(base64Encoded:base64) else { throw TransferFault("CERT","CA证书格式无效") }
            der = decoded
        } else { der = caData }
        guard let anchor = SecCertificateCreateWithData(nil,der as CFData) else { throw TransferFault("CERT","无法读取CA证书") }
        var items: CFArray?
        var importOptions: [String:Any] = [kSecImportExportPassphrase as String:credentials.password]
        if #available(macOS 15.0, *) { importOptions[kSecImportToMemoryOnly as String] = true }
        let status = SecPKCS12Import(try Data(contentsOf:credentials.identity) as CFData,importOptions as CFDictionary,&items)
        guard status == errSecSuccess, let first = (items as? [[String:Any]])?.first,
              let rawIdentity = first[kSecImportItemIdentity as String] else {
            throw TransferFault("CERT","客户端身份读取失败，请检查P12文件及密码（\(status)）")
        }
        let identity = rawIdentity as! SecIdentity
        guard let local = sec_identity_create(identity) else { throw TransferFault("CERT","无法加载客户端身份") }
        let tls = NWProtocolTLS.Options()
        sec_protocol_options_set_min_tls_protocol_version(tls.securityProtocolOptions,.TLSv12)
        sec_protocol_options_set_tls_server_name(tls.securityProtocolOptions,credentials.host)
        sec_protocol_options_set_local_identity(tls.securityProtocolOptions,local)
        sec_protocol_options_set_verify_block(tls.securityProtocolOptions,{ _,trust,complete in
            let evaluation = sec_trust_copy_ref(trust).takeRetainedValue()
            let policy = SecPolicyCreateSSL(true,credentials.host as CFString)
            guard SecTrustSetPolicies(evaluation,policy) == errSecSuccess,
                  SecTrustSetAnchorCertificates(evaluation,[anchor] as CFArray) == errSecSuccess,
                  SecTrustSetAnchorCertificatesOnly(evaluation,true) == errSecSuccess else { complete(false); return }
            var error: CFError?
            complete(SecTrustEvaluateWithError(evaluation,&error))
        },DispatchQueue(label:"edu.ucas.ex1b.trust"))
        let tcp = NWProtocolTCP.Options()
        tcp.enableKeepalive = true
        tcp.keepaliveIdle = 30; tcp.keepaliveInterval = 10; tcp.keepaliveCount = 3
        tcp.noDelay = true; tcp.connectionTimeout = 10
        return NWParameters(tls:tls,tcp:tcp)
    }
}
