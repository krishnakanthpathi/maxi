// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MaxiHUD",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "MaxiHUD", targets: ["MaxiHUD"])
    ],
    targets: [
        .executableTarget(
            name: "MaxiHUD",
            path: "Sources/MaxiHUD"
        )
    ]
)
