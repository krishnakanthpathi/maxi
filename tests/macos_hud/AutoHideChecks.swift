import AppKit
import SwiftUI

@MainActor
enum AutoHideChecks {
    static func until(_ label: String, _ condition: () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(2)
        while !condition(), Date() < deadline { try await Task.sleep(nanoseconds: 2_000_000) }
        precondition(condition(), label)
    }

    static func run() async throws {
        let suite = "MaxiHUDTests." + UUID().uuidString
        let preferences = UserDefaults(suiteName: suite)!
        defer { preferences.removePersistentDomain(forName: suite) }
        let state = AppState(preferences: preferences, timing: HUDTiming(
            resultDismiss: 0.07, idleDismiss: 0.07, opening: 0.02, collapse: 0.03, closing: 0.04))
        state.alwaysShowIdlePill = false
        state.revealHUD()
        precondition(state.presentationPhase == .opening && state.isPanelVisible)
        try await until("Opening did not expand") { state.presentationPhase == .expanded }
        try await until("Manual open stayed visible forever") { state.presentationPhase == .collapsing }
        precondition(!state.isHUDVisible && state.isPanelVisible)
        try await until("Closing logo phase was skipped") { state.presentationPhase == .closing }
        precondition(state.isPanelVisible)
        try await until("Closing did not remove the window") { !state.isPanelVisible }
        print("PASS: manual open auto-hides through the dismissal phases")

        state.setAutoHide(false)
        state.handleResult(transcript: "Test request", output: "Pinned result", tools: [], latencyMs: 1)
        try await Task.sleep(nanoseconds: 160_000_000)
        precondition(state.showToast && state.agentOutput == "Pinned result" && state.isHUDVisible)
        state.setAutoHide(true)
        precondition(AppState(preferences: preferences).autoHideEnabled)
        try await until("Re-enabling auto-hide did not restart dismissal") { !state.showToast }
        precondition(!state.isHUDVisible)
        print("PASS: toggle off pins; toggle on persists and restarts dismissal")

        state.handleVoiceStart(locked: false)
        state.handleResult(transcript: "Read me", output: "Hovered result", tools: [], latencyMs: 1)
        state.setHovering(true)
        try await Task.sleep(nanoseconds: 160_000_000)
        precondition(state.showToast)
        state.setHovering(false)
        try await until("Hover leave did not resume dismissal") { !state.showToast }
        print("PASS: hover pauses dismissal and leaving resumes it")

        state.handleVoiceStart(locked: false)
        state.handleResult(transcript: "Speak", output: "Speaking result", tools: [], latencyMs: 1)
        state.handleTTSStart()
        try await Task.sleep(nanoseconds: 160_000_000)
        precondition(state.mode == .speaking && state.showToast)
        state.handleTTSStop()
        try await until("Speech end did not resume auto-hide") { !state.showToast }
        print("PASS: speech stays visible until it finishes")

        let initialBands = SpeechWaveform.levels(at: 0)
        let laterBands = SpeechWaveform.levels(at: 0.12)
        precondition(initialBands.count == 5 && laterBands.count == 5)
        precondition(zip(initialBands, laterBands).allSatisfy { abs($0 - $1) > 0.01 })
        precondition((initialBands + laterBands).allSatisfy { $0 >= 0.2 && $0 <= 1 })
        state.handleAudioLevels([0.1, 0.3, 0.9, 0.6, 0.2], locked: false, elapsed: 1)
        precondition(state.audioLevels == [0.1, 0.3, 0.9, 0.6, 0.2])
        state.handleTTSStart()
        precondition(state.mode == .speaking)
        state.handleTTSStop()
        precondition(state.mode != .speaking)
        print("PASS: five speech bands change without mic input; recording still uses live samples")

        state.setAutoHide(false)
        state.revealHUD()
        try await until("Pinned HUD did not expand") { state.presentationPhase == .expanded }
        state.alwaysShowIdlePill = true
        state.dismissToast()
        precondition(!state.isHUDVisible && state.isPanelVisible)
        try await until("Pinned manual close never finished") { !state.isPanelVisible }
        state.handleVoiceStart(locked: true)
        try await until("A new recording did not restore the HUD") { state.presentationPhase == .expanded }
        state.dismissToast()
        state.handleVoiceStart(locked: false)
        try await Task.sleep(nanoseconds: 160_000_000)
        precondition(state.isPanelVisible && state.presentationPhase == .expanded && state.mode == .recording(locked: false))
        state.alwaysShowIdlePill = false
        state.dismissToast()
        try await until("Test cleanup did not close") { !state.isPanelVisible }
        print("PASS: manual close overrides pinning; stale closing tasks cannot hide a new recording")

        state.setAutoHide(true)
        state.handleVoiceStart(locked: false)
        state.handleVoiceStop(cancelled: true, reason: "cancel")
        state.setHovering(true)
        try await until("Hovering a cancelled HUD blocked its reset") { !state.isPanelVisible }
        print("PASS: hovering cancelled work cannot leave the HUD stuck open")

        let screen = CGRect(x: 0, y: 0, width: 1512, height: 982)
        let visible = CGRect(x: 0, y: 40, width: 1512, height: 910)
        precondition(HUDGeometry.topEdge(fullFrame: screen, visibleFrame: visible, safeTop: 32) == 938)
        // Honor the hardware cutout even when the menu bar is hidden.
        precondition(HUDGeometry.topEdge(fullFrame: screen, visibleFrame: screen, safeTop: 32) == 938)
        precondition(HUDGeometry.topEdge(fullFrame: screen, visibleFrame: screen, safeTop: 0) == 970)
        print("PASS: floating pill keeps a gap below the notch, including with the menu bar hidden")

        let size = CGSize(width: 540, height: 400)
        let pill = CGSize(width: 220, height: 40)
        precondition(HUDGeometry.hitSurface(CGPoint(x: 270, y: 20), size: size, pillSize: pill, atTop: true, hasResponse: true))
        precondition(HUDGeometry.hitSurface(CGPoint(x: 270, y: 200), size: size, pillSize: pill, atTop: true, hasResponse: true))
        precondition(!HUDGeometry.hitSurface(CGPoint(x: 270, y: 47), size: size, pillSize: pill, atTop: true, hasResponse: true))
        precondition(!HUDGeometry.hitSurface(CGPoint(x: 10, y: 20), size: size, pillSize: pill, atTop: true, hasResponse: true))
        precondition(HUDGeometry.hitSurface(CGPoint(x: 270, y: 380), size: size, pillSize: pill, atTop: false, hasResponse: true))
        precondition(!HUDGeometry.hitSurface(CGPoint(x: 270, y: 353), size: size, pillSize: pill, atTop: false, hasResponse: true))
        print("PASS: original pill and separate card accept clicks; their gap and surrounding transparency pass through")
    }
}
