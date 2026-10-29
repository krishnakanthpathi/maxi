import AppKit

/// The native app uses the independently installed Python backend for every API.
enum BackendBootstrap {
    enum Outcome: Sendable, Equatable {
        case ready
        case needsSetup
        case failed(String)
    }

    @MainActor private static var isStarting = false

    @MainActor
    static func start(onReady: @escaping @MainActor () -> Void) {
        guard !isStarting else { return }
        isStarting = true
        let resources = Bundle.main.resourceURL
        let root = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".maxi")
        Task {
            let outcome = await Task.detached(priority: .userInitiated) { prepareBackend(root: root) }.value
            isStarting = false
            switch outcome {
            case .ready: onReady()
            case .needsSetup:
                if let setup = resources?.appendingPathComponent("Install Maxi.command"),
                   FileManager.default.fileExists(atPath: setup.path) {
                    if !NSWorkspace.shared.open(setup) {
                        showError("Open Install Maxi.command inside the app’s Resources folder to finish setup.")
                    }
                } else {
                    showError("Install the Python backend wheel first using Maxi’s macOS installer, then reopen Maxi.")
                }
            case .failed(let message): showError(message)
            }
        }
    }

    static func prepareBackend(root: URL) -> Outcome {
        let python = ProcessInfo.processInfo.environment["MAXI_BACKEND_PYTHON"].map { URL(fileURLWithPath: $0) }
            ?? root.appendingPathComponent("venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path),
              FileManager.default.fileExists(atPath: root.path)
        else { return .needsSetup }
        do {
            let check = Process()
            check.executableURL = python
            check.arguments = ["-c", "from importlib.util import find_spec; assert all(find_spec(m) for m in ('app', 'sounddevice', 'pynput', 'numpy'))"]
            check.currentDirectoryURL = root
            check.standardOutput = FileHandle.nullDevice
            check.standardError = FileHandle.nullDevice
            try check.run()
            check.waitUntilExit()
            guard check.terminationStatus == 0 else { return .needsSetup }

            let log = root.appendingPathComponent("launcher.log")
            if !FileManager.default.fileExists(atPath: log.path) {
                FileManager.default.createFile(atPath: log.path, contents: nil)
            }
            let output = try FileHandle(forWritingTo: log)
            defer { try? output.close() }
            output.seekToEndOfFile()
            let daemon = Process()
            daemon.executableURL = python
            daemon.arguments = ["-m", "app.cli", "start", "--for-hud"]
            daemon.currentDirectoryURL = root
            var environment = ProcessInfo.processInfo.environment
            environment["PATH"] = root.appendingPathComponent("venv/bin").path + ":"
                + FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin").path
                + ":" + (environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
            daemon.environment = environment
            daemon.standardOutput = output
            daemon.standardError = output
            try daemon.run()
            daemon.waitUntilExit()
            return daemon.terminationStatus == 0 ? .ready
                : .failed("The backend could not start. Check ~/.maxi/launcher.log or run Maxi’s installer again.")
        } catch {
            return .failed("The backend could not start: \(error.localizedDescription)")
        }
    }

    @MainActor
    private static func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Maxi couldn’t start its backend"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }
}
