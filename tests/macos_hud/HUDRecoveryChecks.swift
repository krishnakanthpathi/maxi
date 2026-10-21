import AppKit
import Foundation

private final class LocalPeer {
    let process = Process()
    let port: Int

    init(mode: String) throws {
        let script = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("ws_peer.py")
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [script.path, mode]
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = output.fileHandleForReading.availableData
        guard let line = String(data: data, encoding: .utf8),
              let port = Int(line.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            process.terminate()
            throw NSError(domain: "LocalPeer", code: 1)
        }
        self.port = port
    }

    deinit {
        if process.isRunning { process.terminate() }
    }

    @MainActor
    func client() -> WebSocketClient {
        WebSocketClient(
            wsURL: URL(string: "ws://127.0.0.1:\(port)/ws")!,
            apiBase: URL(string: "http://127.0.0.1:\(port)/api")!,
            reconnectDelay: 50_000_000,
            heartbeatInterval: 100_000_000,
            heartbeatTimeout: 300_000_000
        )
    }

    func connectionCount() async throws -> Int {
        let (data, _) = try await URLSession.shared.data(from: URL(string: "http://127.0.0.1:\(port)/stats")!)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Int]
        return json["connections"]!
    }
}

@main
struct HUDRecoveryChecks {
    @MainActor
    static func waitUntil(_ label: String, _ condition: () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(4)
        while !condition(), Date() < deadline {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        precondition(condition(), label)
    }

    @MainActor
    static func main() async throws {
        // Use the real panel, not just the view's published visibility flag.
        _ = NSApplication.shared
        let state = AppState.shared
        let panel = BarPanel(contentView: HUDView(state: state))
        state.onLayoutChange = {
            if state.isHUDVisible { panel.orderFrontRegardless() }
            else { panel.orderOut(nil) }
        }
        defer { state.onLayoutChange = nil; panel.orderOut(nil) }
        state.handleVoiceIdle()
        precondition(!panel.isVisible)
        state.transcript = "Keep this on reopen"
        let delegate = AppDelegate()
        precondition(delegate.applicationShouldHandleReopen(NSApplication.shared, hasVisibleWindows: false))
        precondition(panel.isVisible && state.isHUDVisible && state.mode == .idle)
        precondition(state.transcript == "Keep this on reopen")
        state.handleEscape()
        precondition(!panel.isVisible && !state.isManuallyPresented)
        precondition(delegate.applicationShouldHandleReopen(NSApplication.shared, hasVisibleWindows: true))
        precondition(panel.isVisible)
        state.handleVoiceStart(locked: false)
        precondition(!state.isManuallyPresented && panel.isVisible)
        state.handleVoiceIdle()
        precondition(!panel.isVisible)
        print("PASS: explicit open reveals the idle HUD; Escape hides it and voice work restores automatic visibility")
        state.handleAudioLevels([0.2, 0.4, 0.8, 0.4, 0.2], locked: true, elapsed: 2.5)
        precondition(state.mode == .recording(locked: true) && panel.isVisible)
        precondition(state.elapsedSeconds == 2.5)
        state.transcript = "Keep this transcript"
        state.handleAudioLevels([0.3, 0.5, 0.9, 0.5, 0.3], locked: false, elapsed: 2.6)
        precondition(state.transcript == "Keep this transcript")
        precondition(state.mode == .recording(locked: false))
        print("PASS: missed start event restores the actual panel without clearing later transcripts")

        state.handleVoiceStop(cancelled: true, reason: "cancel")
        state.handleAudioLevels([0.5] + Array(repeating: 0.3, count: 4), locked: false, elapsed: 1)
        state.transcript = "New recording"
        try await Task.sleep(nanoseconds: 800_000_000)
        precondition(state.mode == .recording(locked: false) && state.transcript == "New recording")
        print("PASS: previous cancellation cannot dismiss a recovered recording")

        for mode in ["drop-once", "hang-once"] {
            let peer = try LocalPeer(mode: mode)
            let client = peer.client()
            state.handleVoiceIdle()
            client.start()
            try await waitUntil("Failed to recover \(mode)") {
                state.wsConnected && state.mode == .recording(locked: false)
            }
            precondition(panel.isVisible)
            let count = try await peer.connectionCount()
            precondition(count == 2, "Expected one reconnect, got \(count) connections")
            client.stop()
            state.handleVoiceIdle()
            print("PASS: \(mode) reconnects once and displays the ongoing recording")
        }

        let peer = try LocalPeer(mode: "normal")
        let client = peer.client()
        client.start()
        try await waitUntil("Initial connection failed") { state.wsConnected }
        client.reconnect()
        client.reconnect()
        client.reconnect()
        try await waitUntil("Wake reconnection failed") { state.wsConnected }
        try await Task.sleep(nanoseconds: 500_000_000)
        let count = try await peer.connectionCount()
        try await Task.sleep(nanoseconds: 500_000_000)
        let stableCount = try await peer.connectionCount()
        precondition(stableCount == count && state.wsConnected, "Old callbacks started extra retries")
        client.stop()
        try await Task.sleep(nanoseconds: 500_000_000)
        let stoppedCount = try await peer.connectionCount()
        precondition(stoppedCount == count && !state.wsConnected)
        state.handleVoiceIdle()
        print("PASS: repeated wake reconnects ignore old callbacks; stop prevents retries")
    }
}
