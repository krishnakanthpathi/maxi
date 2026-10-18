import SwiftUI
import Combine

enum HUDMode: Equatable {
    case idle
    case recording(locked: Bool)
    case processing
    case speaking
    case result
    case cancelled
}

enum PositionMode: String, CaseIterable {
    case bottomDock = "bottom"
    case topNotch = "top"
}

struct CapturedContextInfo: Equatable {
    var appName: String = ""
    var bundleId: String = ""
    var windowTitle: String = ""
    var url: String = ""
    var selectedText: String = ""

    var hasSelection: Bool {
        !selectedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

@MainActor
final class AppState: ObservableObject {
    static let shared = AppState()

    @Published var mode: HUDMode = .idle
    @Published var audioLevels: [CGFloat] = [0.12, 0.12, 0.12, 0.12, 0.12]
    @Published var elapsedSeconds: Double = 0.0
    @Published var contextInfo: CapturedContextInfo = CapturedContextInfo()

    @Published var transcript: String = ""
    @Published var agentOutput: String = ""
    @Published var toolsUsed: [String] = []
    @Published var currentExecutingTool: String? = nil
    @Published var activeToolsList: [String] = []
    @Published var activeAppIcon: NSImage? = nil
    @Published var activeAppName: String = ""
    @Published var latencyMs: Int = 0
    @Published var showToast: Bool = false
    @Published var isHoveringToast: Bool = false
    @Published var copiedFeedback: Bool = false

    @Published var wsConnected: Bool = false
    @Published var alwaysShowIdlePill: Bool = false
    @Published var positionMode: PositionMode = {
        let saved = UserDefaults.standard.string(forKey: "maxi.hud.position") ?? PositionMode.bottomDock.rawValue
        return PositionMode(rawValue: saved) ?? .bottomDock
    }()

    var isHUDVisible: Bool {
        alwaysShowIdlePill || mode != .idle || showToast
    }

    private var hoverDismissGeneration: Int = 0
    private var dismissTask: Task<Void, Never>?
    var onLayoutChange: (() -> Void)?

    func setPosition(_ newMode: PositionMode) {
        positionMode = newMode
        UserDefaults.standard.set(newMode.rawValue, forKey: "maxi.hud.position")
        onLayoutChange?()
    }

    func captureFrontmostApp() {
        if let frontmost = NSWorkspace.shared.frontmostApplication {
            let name = frontmost.localizedName ?? ""
            let bundle = frontmost.bundleIdentifier ?? ""
            if bundle != Bundle.main.bundleIdentifier {
                self.activeAppName = name
                self.activeAppIcon = frontmost.icon
                self.contextInfo.appName = name
                self.contextInfo.bundleId = bundle
            }
        }
    }

    func handleVoiceStart(locked: Bool) {
        dismissTask?.cancel()
        captureFrontmostApp()
        withAnimation(.spring(response: 0.28, dampingFraction: 0.78)) {
            mode = .recording(locked: locked)
            elapsedSeconds = 0.0
            audioLevels = [0.18, 0.26, 0.34, 0.26, 0.18]
            showToast = false
            currentExecutingTool = nil
            activeToolsList = []
        }
        onLayoutChange?()
    }

    func handleVoiceLock(locked: Bool) {
        withAnimation(.spring(response: 0.25, dampingFraction: 0.75)) {
            mode = .recording(locked: locked)
        }
        onLayoutChange?()
    }

    func handleToolStart(_ tool: String) {
        guard !tool.isEmpty else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
            currentExecutingTool = tool
            if !activeToolsList.contains(tool) {
                activeToolsList.append(tool)
            }
            toolsUsed = activeToolsList
        }
        onLayoutChange?()
    }

    func handleToolEnd(_ tool: String) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
            if currentExecutingTool == tool {
                currentExecutingTool = nil
            }
        }
        onLayoutChange?()
    }

    func handleContextUpdate(_ ctx: CapturedContextInfo) {
        withAnimation(.easeOut(duration: 0.18)) {
            contextInfo = ctx
            if activeAppIcon == nil && !ctx.appName.isEmpty {
                activeAppName = ctx.appName
                activeAppIcon = getAppIcon(for: ctx.appName)
            }
        }
        onLayoutChange?()
    }

    func handleAudioLevels(_ levels: [Double], locked: Bool, elapsed: Double) {
        if case .recording = mode {
            mode = .recording(locked: locked)
        }
        elapsedSeconds = elapsed
        let mapped = levels.prefix(5).map { CGFloat(max(0.10, min(1.0, $0))) }
        if mapped.count == 5 {
            withAnimation(.interactiveSpring(response: 0.09, dampingFraction: 0.65)) {
                audioLevels = Array(mapped)
            }
        }
    }

    func handleVoiceStop(cancelled: Bool, reason: String) {
        audioLevels = [0.12, 0.12, 0.12, 0.12, 0.12]
        if cancelled {
            if reason == "short_tap" {
                withAnimation(.easeOut(duration: 0.15)) {
                    mode = .idle
                    showToast = false
                }
                onLayoutChange?()
            } else {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
                    mode = .cancelled
                    showToast = false
                }
                onLayoutChange?()
                scheduleResetToIdle(after: 0.65)
            }
        }
    }

    func handleVoiceIdle() {
        dismissTask?.cancel()
        currentExecutingTool = nil
        activeToolsList = []
        withAnimation(.easeOut(duration: 0.2)) {
            mode = .idle
            showToast = false
        }
        onLayoutChange?()
    }

    func handleProcessing() {
        withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
            mode = .processing
            audioLevels = [0.12, 0.12, 0.12, 0.12, 0.12]
        }
        onLayoutChange?()
    }

    func handleTranscript(_ text: String) {
        withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
            transcript = text
            showToast = true
        }
        onLayoutChange?()
    }

    func handleResult(transcript: String, output: String, tools: [String], latencyMs: Int) {
        withAnimation(.spring(response: 0.32, dampingFraction: 0.82)) {
            if !transcript.isEmpty {
                self.transcript = transcript
            }
            self.agentOutput = output
            self.toolsUsed = tools.isEmpty ? self.activeToolsList : tools
            self.currentExecutingTool = nil
            self.latencyMs = latencyMs
            self.mode = .result
            self.showToast = true
        }
        onLayoutChange?()
        scheduleAutoDismiss(after: 4.0)
    }

    func handleTTSStart() {
        dismissTask?.cancel()
        withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
            mode = .speaking
        }
        onLayoutChange?()
    }

    func handleTTSStop() {
        if mode == .speaking {
            withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
                mode = showToast ? .result : .idle
            }
            onLayoutChange?()
            if showToast {
                scheduleAutoDismiss(after: 2.2)
            }
        }
    }

    func setHovering(_ hovering: Bool) {
        isHoveringToast = hovering
        hoverDismissGeneration += 1
        if hovering {
            dismissTask?.cancel()
        } else if showToast && (mode == .result || mode == .idle) {
            scheduleAutoDismiss(after: 3.5)
        }
    }

    func dismissToast() {
        dismissTask?.cancel()
        currentExecutingTool = nil
        activeToolsList = []
        withAnimation(.spring(response: 0.26, dampingFraction: 0.82)) {
            showToast = false
            mode = .idle
        }
        onLayoutChange?()
    }

    private func scheduleResetToIdle(after seconds: Double) {
        dismissTask?.cancel()
        dismissTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            withAnimation(.spring(response: 0.28, dampingFraction: 0.82)) {
                if mode == .cancelled {
                    mode = .idle
                }
            }
            onLayoutChange?()
        }
    }

    private func scheduleAutoDismiss(after seconds: Double) {
        dismissTask?.cancel()
        let gen = hoverDismissGeneration
        dismissTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard !isHoveringToast && gen == hoverDismissGeneration else { return }
            withAnimation(.spring(response: 0.30, dampingFraction: 0.84)) {
                showToast = false
                if mode == .result {
                    mode = .idle
                }
            }
            onLayoutChange?()
        }
    }
}
