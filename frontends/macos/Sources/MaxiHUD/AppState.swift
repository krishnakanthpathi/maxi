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
    @Published var currentToolArgs: [String: Any] = [:]
    @Published var activeToolsList: [String] = []
    @Published var activeAppIcon: NSImage? = nil
    @Published var activeAppName: String = ""
    @Published var latencyMs: Int = 0
    @Published var showToast: Bool = false
    @Published var isHoveringToast: Bool = false
    @Published var copiedFeedback: Bool = false
    @Published var copiedPromptFeedback: Bool = false
    @Published var contextClearedFeedback: Bool = false

    @Published var qrImage: NSImage? = nil
    @Published var qrCountdown: Int = 20
    @Published var qrFilePath: String? = nil
    private var qrTimer: Timer? = nil
    private var lastQRModDate: Date? = nil

    @Published var wsConnected: Bool = false
    @Published var currentModel: String = "gpt-oss:120b-cloud"
    @Published var availableModels: [String] = [
        "gpt-oss:120b-cloud",
        "gemma4:31b-cloud",
        "llama-3.3-70b-versatile",
        "meta-llama/llama-3.3-70b-instruct"
    ]
    @Published var alwaysShowIdlePill: Bool = false
    @Published var isManuallyPresented: Bool = false
    @Published var autoSpeechEnabled: Bool = {
        if UserDefaults.standard.object(forKey: "maxi.hud.auto_speech") != nil {
            return UserDefaults.standard.bool(forKey: "maxi.hud.auto_speech")
        }
        return true
    }()
    @Published var autoHideEnabled: Bool = {
        if UserDefaults.standard.object(forKey: "maxi.hud.auto_hide") != nil {
            return UserDefaults.standard.bool(forKey: "maxi.hud.auto_hide")
        }
        return true
    }()
    @Published var positionMode: PositionMode = {
        let saved = UserDefaults.standard.string(forKey: "maxi.hud.position") ?? PositionMode.topNotch.rawValue
        return PositionMode(rawValue: saved) ?? .topNotch
    }()

    var isHUDVisible: Bool {
        alwaysShowIdlePill || isManuallyPresented || mode != .idle || showToast
    }

    func revealHUD() {
        isManuallyPresented = true
        onLayoutChange?()
    }

    private var hoverDismissGeneration: Int = 0
    private var dismissTask: Task<Void, Never>?
    var onLayoutChange: (() -> Void)?

    func setPosition(_ newMode: PositionMode) {
        positionMode = newMode
        UserDefaults.standard.set(newMode.rawValue, forKey: "maxi.hud.position")
        onLayoutChange?()
    }

    func setAutoSpeech(_ enabled: Bool) {
        autoSpeechEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: "maxi.hud.auto_speech")
        WebSocketClient.shared.setAutoSpeech(enabled: enabled)
        onLayoutChange?()
    }

    func toggleAutoSpeech() {
        setAutoSpeech(!autoSpeechEnabled)
    }

    func setAutoHide(_ enabled: Bool) {
        autoHideEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: "maxi.hud.auto_hide")
        if !enabled {
            dismissTask?.cancel()
        }
        onLayoutChange?()
    }

    func toggleAutoHide() {
        setAutoHide(!autoHideEnabled)
    }

    func clearContext() {
        dismissTask?.cancel()
        stopQRPoll()
        WebSocketClient.shared.clearContext()
        withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) {
            contextClearedFeedback = true
            mode = .idle
            showToast = false
            audioLevels = [0.12, 0.12, 0.12, 0.12, 0.12]
            transcript = ""
            agentOutput = ""
            toolsUsed = []
            activeToolsList = []
            currentExecutingTool = nil
            currentToolArgs = [:]
            contextInfo = CapturedContextInfo()
            activeAppIcon = nil
            activeAppName = ""
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { [weak self] in
            self?.contextClearedFeedback = false
        }
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
        isManuallyPresented = false
        dismissTask?.cancel()
        stopQRPoll()
        captureFrontmostApp()
        withAnimation(.spring(response: 0.28, dampingFraction: 0.78)) {
            mode = .recording(locked: locked)
            elapsedSeconds = 0.0
            audioLevels = [0.18, 0.26, 0.34, 0.26, 0.18]
            showToast = false
            currentExecutingTool = nil
            activeToolsList = []
            toolsUsed = []
            transcript = ""
            agentOutput = ""
            latencyMs = 0
        }
        onLayoutChange?()
    }

    func handleVoiceLock(locked: Bool) {
        withAnimation(.spring(response: 0.25, dampingFraction: 0.75)) {
            mode = .recording(locked: locked)
        }
        onLayoutChange?()
    }

    func handleToolStart(_ tool: String, args: [String: Any] = [:]) {
        guard !tool.isEmpty else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
            currentExecutingTool = tool
            currentToolArgs = args
            activeToolsList.append(tool)
            toolsUsed = activeToolsList
        }
        onLayoutChange?()
    }

    func handleToolEnd(_ tool: String) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
            if currentExecutingTool == tool {
                currentExecutingTool = nil
                currentToolArgs = [:]
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
        } else {
            // A reconnect can miss voice_start. Live levels also prove that a
            // recording is active, so restore the panel and cancel old dismissals.
            handleVoiceStart(locked: locked)
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
                    transcript = ""
                    agentOutput = ""
                }
                onLayoutChange?()
            } else {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
                    mode = .cancelled
                    showToast = false
                    transcript = ""
                    agentOutput = ""
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
            transcript = ""
            agentOutput = ""
        }
        onLayoutChange?()
    }

    func handleProcessing() {
        isManuallyPresented = false
        withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
            mode = .processing
            audioLevels = [0.12, 0.12, 0.12, 0.12, 0.12]
            showToast = false
            currentExecutingTool = nil
            currentToolArgs = [:]
            activeToolsList = []
            toolsUsed = []
            agentOutput = ""
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

    func startQRPoll(path: String) {
        self.qrFilePath = path
        loadFreshQR()
        qrTimer?.invalidate()
        qrTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                self.loadFreshQR()
                if self.qrCountdown > 1 {
                    self.qrCountdown -= 1
                } else {
                    self.qrCountdown = 20
                }
            }
        }
    }

    func stopQRPoll() {
        qrTimer?.invalidate()
        qrTimer = nil
        qrImage = nil
        qrFilePath = nil
        lastQRModDate = nil
    }

    private func loadFreshQR() {
        guard let path = qrFilePath, FileManager.default.fileExists(atPath: path) else { return }
        let url = URL(fileURLWithPath: path)
        do {
            let attrs = try FileManager.default.attributesOfItem(atPath: path)
            let modDate = attrs[.modificationDate] as? Date ?? Date()
            if qrImage == nil || lastQRModDate == nil || modDate > lastQRModDate! {
                let data = try Data(contentsOf: url, options: .uncached)
                if let img = NSImage(data: data) {
                    self.qrImage = img
                    self.lastQRModDate = modDate
                    self.qrCountdown = 20
                }
            }
        } catch {}
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

        // An explicit result image remains valid after status checks or login.
        // Tool names alone do not identify a fresh QR code or its location.
        let foundPath = ResultImage.path(in: output)

        if let path = foundPath {
            startQRPoll(path: path)
            scheduleAutoDismiss(after: 180.0)
        } else {
            stopQRPoll()
            scheduleAutoDismiss(after: 4.0)
        }

        onLayoutChange?()
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

    func handleEscape() {
        if mode == .idle && isManuallyPresented && !showToast {
            isManuallyPresented = false
            onLayoutChange?()
            return
        }
        isManuallyPresented = false
        dismissTask?.cancel()
        stopQRPoll()
        WebSocketClient.shared.cancelActiveCommand()
        if mode == .speaking {
            WebSocketClient.shared.stopTTS()
        }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
            mode = .cancelled
            showToast = false
            currentExecutingTool = nil
            currentToolArgs = [:]
            activeToolsList = []
            toolsUsed = []
            transcript = ""
            agentOutput = ""
        }
        onLayoutChange?()
        scheduleResetToIdle(after: 0.5)
    }

    func dismissToast() {
        dismissTask?.cancel()
        stopQRPoll()
        currentExecutingTool = nil
        activeToolsList = []
        if mode == .speaking {
            WebSocketClient.shared.stopTTS()
        }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.82)) {
            showToast = false
            mode = .idle
            transcript = ""
            agentOutput = ""
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
                transcript = ""
                agentOutput = ""
            }
            onLayoutChange?()
        }
    }

    private func scheduleAutoDismiss(after seconds: Double) {
        dismissTask?.cancel()
        guard autoHideEnabled else { return }
        let effectiveSeconds = (qrFilePath != nil && seconds < 180.0) ? 180.0 : seconds
        let gen = hoverDismissGeneration
        dismissTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(effectiveSeconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard !isHoveringToast && gen == hoverDismissGeneration else { return }
            guard autoHideEnabled else { return }
            stopQRPoll()
            withAnimation(.spring(response: 0.30, dampingFraction: 0.84)) {
                showToast = false
                if mode == .result {
                    mode = .idle
                }
                transcript = ""
                agentOutput = ""
            }
            onLayoutChange?()
        }
    }
}
