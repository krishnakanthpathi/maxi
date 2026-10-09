// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MaxiHUD",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "MaxiHUD",
            targets: ["MaxiHUD"]
        )
    ],
    dependencies: [],
    targets: [
        .executableTarget(
            name: "MaxiHUD",
            dependencies: [],
            path: "Sources/MaxiHUD"
        )
    ]
)
