import AppKit
import SwiftUI

/// Render the real SwiftUI hierarchy with synthetic content, without any backend calls.
@main
struct HUDPreview {
    @MainActor
    static func main() {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)
        Task { @MainActor in
            do { try await render() }
            catch { fatalError("HUD preview failed: \(error)") }
            NSApp.terminate(nil)
        }
        NSApp.run()
    }

    @MainActor
    static func render() async throws {
        let target = CommandLine.arguments.dropFirst().first(where: { !$0.hasPrefix("--") }) ?? "/tmp/maxi-native-preview"
        let output = URL(fileURLWithPath: target, isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let state = AppState.shared
        state.autoHideEnabled = false
        state.wsConnected = true
        state.positionMode = .topNotch
        state.updateNotch(width: 200, height: 30)
        let panel = BarPanel(contentView: HUDView(state: state))
        panel.setFrame(NSRect(x: -10000, y: -10000, width: 780, height: 600), display: false)
        state.onLayoutChange = {
            if state.isPanelVisible { panel.orderFrontRegardless() } else { panel.orderOut(nil) }
        }
        defer { panel.orderOut(nil); state.onLayoutChange = nil }
        state.revealHUD()
        try await Task.sleep(nanoseconds: 650_000_000)
        try snapshot(panel, to: output.appendingPathComponent("idle-hint.png"))
        precondition(state.renderedSize.width > 120 && state.renderedSize.height < 60)
        try snapshot(panel, to: output.appendingPathComponent("notch-idle.png"))
        state.handleResult(transcript: "Summarize the changes to Maxi.",
                           output: "**The original Maxi layout.**\n\nThe compact glass pill sits above a separate response card, both with a static ∑ logo.\n\nPin a response to keep it visible, or use Escape to dismiss it.",
                           tools: [], latencyMs: 480)
        try await Task.sleep(nanoseconds: 650_000_000)
        precondition(state.renderedSize.height > 180, "Expanded result must have a visible body")
        let host = panel.contentView!
        for y in [state.pillSize.height / 2, state.renderedSize.height - 28] {
            let local = NSPoint(x: host.bounds.midX,
                                y: host.isFlipped ? y : host.bounds.height - y)
            precondition(host.hitTest(host.convert(local, to: host.superview)) != nil,
                         "Visible header/copy controls must receive mouse hits")
        }
        let outside = NSPoint(x: host.bounds.minX + 2, y: host.bounds.midY)
        precondition(host.hitTest(host.convert(outside, to: host.superview)) == nil,
                     "The transparent area must pass mouse hits through")
        print("PASS: visible header and response controls receive hits; transparent panel space passes through")
        try snapshot(panel, to: output.appendingPathComponent("notch-expanded.png"))
        state.handleResult(transcript: "A long response", output: Array(repeating: "This paragraph verifies that long responses scroll inside the connected panel while its controls stay visible.", count: 20).joined(separator: "\n\n"), tools: [], latencyMs: 480)
        try await Task.sleep(nanoseconds: 650_000_000)
        precondition(state.renderedSize.height <= state.maximumBodyHeight + state.pillSize.height + HUDGeometry.cardGap + 60,
                     "Long content must fit inside the screen-height cap")
        try snapshot(panel, to: output.appendingPathComponent("notch-long-response.png"))
        state.handleResult(transcript: "Summarize the changes to Maxi.",
                           output: "**The original Maxi layout.**\n\nThe pill and response card are separate again, with the original controls.\n\nThe sigma stays still while idle, hovering, opening and closing.",
                           tools: [], latencyMs: 480)
        state.positionMode = .bottomDock
        state.refreshPresentation()
        try await Task.sleep(nanoseconds: 650_000_000)
        try snapshot(panel, to: output.appendingPathComponent("bottom-expanded.png"))
        print("Rendered native HUD previews at \(output.path)")
        if CommandLine.arguments.contains("--markdown") {
            state.handleResult(transcript: "Show Markdown, code and an HTML preview.", output: """
            ## Rich responses
            | Feature | Status |
            | :--- | ---: |
            | Markdown tables | Ready |
            | Code copying | Ready |

            ```python
            print("Hello from Maxi")
            ```

            ```html
            <style>button {padding: 14px 24px; border-radius:12px; background:#282c45; color:white; border:0}</style>
            <h2>A live HTML preview</h2>
            <button onclick="this.textContent = 'Count: ' + (++window.count)">Count: 0</button>
            <script>window.count = 0</script>
            ```

            - [x] Headings, lists and tables
            - [x] Syntax highlighting and code copying
            - [x] Interactive HTML previews
            """, tools: [], latencyMs: 420)
            state.positionMode = .topNotch
            state.refreshPresentation()
        }
        if CommandLine.arguments.contains("--hold") {
            state.positionMode = .topNotch
            panel.updatePosition()
            state.refreshPresentation()
            if CommandLine.arguments.contains("--speaking") { state.handleTTSStart() }
            for _ in 0..<600 { try await Task.sleep(nanoseconds: 1_000_000_000) }
        }
    }

    @MainActor
    static func snapshot(_ panel: NSPanel, to url: URL) throws {
        let view = panel.contentView!
        view.layoutSubtreeIfNeeded()
        view.needsDisplay = true
        view.displayIfNeeded()
        let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds)!
        view.cacheDisplay(in: view.bounds, to: bitmap)
        try bitmap.representation(using: .png, properties: [:])!.write(to: url)
    }
}
