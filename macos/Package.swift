// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SafeTransfer",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "SafeTransfer", targets: ["SafeTransferApp"]),
        .executable(name: "TransferProbe", targets: ["TransferProbe"]),
        .library(name: "SafeTransferCore", targets: ["SafeTransferCore"])
    ],
    targets: [
        .target(name: "SafeTransferCore"),
        .executableTarget(name: "SafeTransferApp", dependencies: ["SafeTransferCore"]),
        .executableTarget(name: "TransferProbe", dependencies: ["SafeTransferCore"]),
        .testTarget(name: "SafeTransferCoreTests", dependencies: ["SafeTransferCore"])
    ],
    swiftLanguageModes: [.v5]
)
