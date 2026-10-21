import AppKit
import Darwin

// A native launcher keeps the app launchable without a system Python or Xcode.
let contents = Bundle.main.bundleURL.appendingPathComponent("Contents")
let resources = contents.appendingPathComponent("Resources")
let home = FileManager.default.homeDirectoryForCurrentUser
let root = home.appendingPathComponent(".maxi")
let python = root.appendingPathComponent("venv/bin/python")
let config = root.appendingPathComponent(".env")
let log = root.appendingPathComponent("launcher.log")

func fail(_ message: String) -> Never {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    app.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "Maxi couldn’t start"
    alert.informativeText = message
    alert.addButton(withTitle: "OK")
    alert.runModal()
    exit(1)
}

func backendIsInstalled() -> Bool {
    guard FileManager.default.isExecutableFile(atPath: python.path),
        FileManager.default.fileExists(atPath: config.path) else { return false }
    let check = Process()
    check.executableURL = python
    check.arguments = ["-c", "from importlib.util import find_spec; assert all(find_spec(m) for m in ('app', 'sounddevice', 'pynput', 'numpy'))"]
    check.standardOutput = FileHandle.nullDevice
    check.standardError = FileHandle.nullDevice
    do { try check.run(); check.waitUntilExit(); return check.terminationStatus == 0 }
    catch { return false }
}

if !backendIsInstalled() {
    let setup = resources.appendingPathComponent("Install Maxi.command")
    guard NSWorkspace.shared.open(setup) else {
        fail("Open Install Maxi.command inside the app’s Resources folder to finish setup.")
    }
    exit(0)
}

do {
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    if !FileManager.default.fileExists(atPath: log.path) {
        FileManager.default.createFile(atPath: log.path, contents: nil)
    }
    let output = try FileHandle(forWritingTo: log)
    output.seekToEndOfFile()
    let daemon = Process()
    daemon.executableURL = python
    daemon.arguments = ["-m", "app.cli", "start"]
    daemon.currentDirectoryURL = root
    var environment = ProcessInfo.processInfo.environment
    environment["PATH"] = root.appendingPathComponent("venv/bin").path + ":"
        + home.appendingPathComponent(".local/bin").path + ":"
        + (environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
    daemon.environment = environment
    daemon.standardOutput = output
    daemon.standardError = output
    try daemon.run()
    daemon.waitUntilExit()
    try output.close()
    if daemon.terminationStatus != 0 {
        fail("The backend could not start. Check ~/.maxi/launcher.log or run Maxi’s installer again.")
    }
} catch {
    fail("The backend could not start: \(error.localizedDescription)")
}

let hud = contents.appendingPathComponent("MacOS/MaxiHUD").path
let arguments = [strdup(hud), nil]
arguments.withUnsafeBufferPointer { buffer in _ = execv(hud, buffer.baseAddress!) }
fail("The native HUD is missing or incompatible with this Mac. Install Maxi again.")
