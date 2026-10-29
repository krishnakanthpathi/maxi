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

enum HUDPresentationPhase: Equatable {
    case hidden, opening, expanded, collapsing, closing
}

struct HUDTiming {
    var resultDismiss: Double = 4.0
    var idleDismiss: Double = 3.5
    var opening: Double = 0.24
    var collapse: Double = 0.22
    var closing: Double = 0.28
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
    @Published var isStreamingTTSAudio: Bool = false
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
    @Published var currentModel: String = "gemma2:31b-cloud"
    @Published var availableModels: [String] = [
        "gemma2:31b-cloud",
        "gpt-oss:120b-cloud",
        "llama-3.3-70b-versatile",
        "meta-llama/llama-3.3-70b-instruct"
    ]
    @Published var alwaysShowIdlePill = false
    @Published var isManuallyPresented: Bool = false
    @Published var autoSpeechEnabled = true
    @Published var autoHideEnabled = true
    @Published var positionMode: PositionMode = .topNotch
    @Published private(set) var presentationPhase: HUDPresentationPhase = .hidden
    @Published private(set) var notchWidth: CGFloat = 200
    @Published private(set) var notchHeight: CGFloat = 30
    @Published private(set) var maximumBodyHeight: CGFloat = 440
    var renderedSize = CGSize(width: 460, height: 100)
    var pillSize = CGSize(width: 220, height: 40)
    private var explicitlyDismissed = false
    private var presentationTask: Task<Void, Never>?
    private let preferences: UserDefaults
    private let timing: HUDTiming

    init(preferences: UserDefaults = .standard, timing: HUDTiming = HUDTiming()) {
        self.preferences = preferences
        self.timing = timing
        autoSpeechEnabled = preferences.object(forKey: "maxi.hud.auto_speech") as? Bool ?? true
        autoHideEnabled = preferences.object(forKey: "maxi.hud.auto_hide") as? Bool ?? true
        alwaysShowIdlePill = preferences.object(forKey: "maxi.hud.show_idle_pill") as? Bool ?? false
        positionMode = PositionMode(rawValue: preferences.string(forKey: "maxi.hud.position") ?? "top") ?? .topNotch
    }

    var isHUDVisible: Bool {
        !explicitlyDismissed && (!autoHideEnabled || alwaysShowIdlePill || isManuallyPresented || mode != .idle || showToast)
    }

    // Keep the native window alive until the closing animation has finished.
    var isPanelVisible: Bool { isHUDVisible || presentationPhase != .hidden }
    var isIdlePresentation: Bool { mode == .idle && !showToast }

    func setAlwaysShowIdle(_ enabled: Bool) {
        alwaysShowIdlePill = enabled
        preferences.set(enabled, forKey: "maxi.hud.show_idle_pill")
        refreshPresentation()
    }

    func revealHUD() {
        explicitlyDismissed = false
        isManuallyPresented = true
        refreshPresentation()
        if mode == .idle && !showToast { scheduleIdleDismiss() }
    }

    func updateNotch(width: CGFloat, height: CGFloat, bodyHeight: CGFloat = 440) {
        if notchWidth != width { notchWidth = width }
        if notchHeight != height { notchHeight = height }
        if maximumBodyHeight != bodyHeight { maximumBodyHeight = bodyHeight }
    }

    func refreshPresentation() {
        if isHUDVisible {
            if presentationPhase == .hidden || presentationPhase == .collapsing || presentationPhase == .closing {
                presentationTask?.cancel()
                presentationPhase = .opening
                presentationTask = Task { @MainActor in
                    do { try await Task.sleep(nanoseconds: UInt64(timing.opening * 1_000_000_000)) }
                    catch { return }
                    guard isHUDVisible else { return }
                    presentationPhase = .expanded
                    onLayoutChange?()
                }
            }
        } else if presentationPhase == .opening || presentationPhase == .expanded {
            presentationTask?.cancel()
            presentationPhase = .collapsing
            presentationTask = Task { @MainActor in
                do { try await Task.sleep(nanoseconds: UInt64(timing.collapse * 1_000_000_000)) }
                catch { return }
                guard !isHUDVisible else { return }
                presentationPhase = .closing
                onLayoutChange?()
                do { try await Task.sleep(nanoseconds: UInt64(timing.closing * 1_000_000_000)) }
                catch { return }
                guard !isHUDVisible else { return }
                presentationPhase = .hidden
                isHoveringToast = false
                onLayoutChange?()
            }
        }
        onLayoutChange?()
    }

    private var hoverDismissGeneration: Int = 0
    private var dismissTask: Task<Void, Never>?
    var onLayoutChange: (() -> Void)?

    func setPosition(_ newMode: PositionMode) {
        positionMode = newMode
        preferences.set(newMode.rawValue, forKey: "maxi.hud.position")
        refreshPresentation()
    }

    func setAutoSpeech(_ enabled: Bool) {
        guard wsConnected else { return }
        WebSocketClient.shared.setAutoSpeech(enabled: enabled) { [weak self] in
            Task { @MainActor in
                guard let self else { return }
                self.autoSpeechEnabled = enabled
                self.preferences.set(enabled, forKey: "maxi.hud.auto_speech")
                self.refreshPresentation()
            }
        }
    }

    func toggleAutoSpeech() {
        setAutoSpeech(!autoSpeechEnabled)
    }

    func setAutoHide(_ enabled: Bool) {
        autoHideEnabled = enabled
        preferences.set(enabled, forKey: "maxi.hud.auto_hide")
        dismissTask?.cancel()
        if enabled {
            if showToast && (mode == .result || mode == .idle) {
                scheduleAutoDismiss(after: timing.resultDismiss)
            } else if mode == .idle {
                isManuallyPresented = true
                scheduleIdleDismiss()
            }
        }
        refreshPresentation()
    }

    func toggleAutoHide() {
        setAutoHide(!autoHideEnabled)
    }

    @Published var configReloadFeedback: Bool = false

    func openEnvConfig() {
        let path = NSString(string: "~/.maxi/.env").expandingTildeInPath
        let url = URL(fileURLWithPath: path)
        let fm = FileManager.default
        if !fm.fileExists(atPath: path) {
            let dir = NSString(string: "~/.maxi").expandingTildeInPath
            try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)
            fm.createFile(atPath: path, contents: nil)
        }
        if !NSWorkspace.shared.open(url) {
            if let textEditURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.TextEdit") {
                NSWorkspace.shared.open([url], withApplicationAt: textEditURL, configuration: NSWorkspace.OpenConfiguration(), completionHandler: nil)
            } else {
                _ = NSWorkspace.shared.open(url)
            }
        }
    }

    func reloadConfig() {
        WebSocketClient.shared.reloadDaemon { [weak self] in
            Task { @MainActor in
                self?.configReloadFeedback = true
                self?.revealHUD()
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                    self?.configReloadFeedback = false
                }
            }
        }
    }

    func restartMaxi() {
        if wsConnected {
            WebSocketClient.shared.restartDaemon()
        } else {
            BackendBootstrap.start {
                WebSocketClient.shared.reconnect()
            }
        }
    }

    func clearContext() {
        guard wsConnected else { return }
        WebSocketClient.shared.clearContext { [weak self] in
            Task { @MainActor in self?.applyContextCleared() }
        }
    }

    private func applyContextCleared() {
        dismissTask?.cancel()
        stopQRPoll()
        isManuallyPresented = true
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
        scheduleIdleDismiss()
        refreshPresentation()
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
        explicitlyDismissed = false
        isManuallyPresented = false
        isHoveringToast = false
        hoverDismissGeneration += 1
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
        refreshPresentation()
    }

    func handleVoiceLock(locked: Bool) {
        withAnimation(.spring(response: 0.25, dampingFraction: 0.75)) {
            mode = .recording(locked: locked)
        }
        refreshPresentation()
    }

    func handleToolStart(_ tool: String, args: [String: Any] = [:]) {
        guard !tool.isEmpty else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
            currentExecutingTool = tool
            currentToolArgs = args
            activeToolsList.append(tool)
            toolsUsed = activeToolsList
        }
        refreshPresentation()
    }

    func handleToolEnd(_ tool: String) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
            if currentExecutingTool == tool {
                currentExecutingTool = nil
                currentToolArgs = [:]
            }
        }
        refreshPresentation()
    }

    func handleContextUpdate(_ ctx: CapturedContextInfo) {
        withAnimation(.easeOut(duration: 0.18)) {
            contextInfo = ctx
            if activeAppIcon == nil && !ctx.appName.isEmpty {
                activeAppName = ctx.appName
                activeAppIcon = getAppIcon(for: ctx.appName)
            }
        }
        refreshPresentation()
    }

    func handleAudioLevels(_ levels: [Double], locked: Bool, elapsed: Double, isSpeaking: Bool = false) {
        if isSpeaking || mode == .speaking {
            isStreamingTTSAudio = true
        } else if case .recording = mode {
            mode = .recording(locked: locked)
        } else if mode == .idle || mode == .cancelled {
            // A reconnect can miss voice_start. Live levels also prove that a
            // recording is active, so restore the panel and cancel old dismissals.
            handleVoiceStart(locked: locked)
        } else {
            return
        }
        elapsedSeconds = elapsed
        let mapped = levels.prefix(5).map { CGFloat(max(0.10, min(1.0, $0))) }
        if mapped.count == 5 {
            audioLevels = Array(mapped)
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
                refreshPresentation()
            } else {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) {
                    mode = .cancelled
                    showToast = false
                    transcript = ""
                    agentOutput = ""
                }
                refreshPresentation()
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
        refreshPresentation()
    }

    func handleProcessing() {
        explicitlyDismissed = false
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
        refreshPresentation()
    }

    func handleTranscript(_ text: String) {
        explicitlyDismissed = false
        withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
            transcript = text
            showToast = true
        }
        refreshPresentation()
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
        explicitlyDismissed = false
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
            // When auto-speech is active in normal use (resultDismiss > 0.5s), give synthesis a 20s
            // window so the HUD does not auto-close before Maxi speaks. handleTTSStop will schedule
            // the final dismissal after speech completes. In fast unit tests, use timing.resultDismiss directly.
            let delay = (autoSpeechEnabled && timing.resultDismiss > 0.5) ? 20.0 : timing.resultDismiss
            scheduleAutoDismiss(after: delay)
        }

        refreshPresentation()
    }

    func handleTTSStart() {
        dismissTask?.cancel()
        explicitlyDismissed = false
        isStreamingTTSAudio = false
        audioLevels = [0.12, 0.12, 0.12, 0.12, 0.12]
        withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
            mode = .speaking
            if !agentOutput.isEmpty || !transcript.isEmpty {
                showToast = true
            }
        }
        refreshPresentation()
    }

    func handleTTSStop() {
        isStreamingTTSAudio = false
        audioLevels = [0.12, 0.12, 0.12, 0.12, 0.12]
        if mode == .speaking {
            withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
                mode = showToast ? .result : .idle
            }
            refreshPresentation()
            if showToast {
                scheduleAutoDismiss(after: timing.resultDismiss)
            }
        }
    }

    func setHovering(_ hovering: Bool) {
        isHoveringToast = hovering
        hoverDismissGeneration += 1
        if hovering && (mode == .result || mode == .idle || mode == .speaking) {
            dismissTask?.cancel()
        } else if showToast && (mode == .result || mode == .idle) {
            scheduleAutoDismiss(after: timing.resultDismiss)
        } else if mode == .idle && isManuallyPresented {
            scheduleIdleDismiss()
        }
    }

    func handleEscape() {
        explicitlyDismissed = true
        if mode == .idle && isManuallyPresented && !showToast {
            isManuallyPresented = false
            refreshPresentation()
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
        refreshPresentation()
        scheduleResetToIdle(after: 0.5)
    }

    func dismissToast() {
        explicitlyDismissed = true
        isManuallyPresented = false
        dismissTask?.cancel()
        stopQRPoll()
        currentExecutingTool = nil
        activeToolsList = []
        switch mode {
        case .processing, .recording, .speaking: WebSocketClient.shared.cancelActiveCommand()
        default: break
        }
        if mode == .speaking {
            WebSocketClient.shared.stopTTS()
        }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.82)) {
            showToast = false
            mode = .idle
            transcript = ""
            agentOutput = ""
        }
        refreshPresentation()
    }

    func toggleResult() {
        guard !transcript.isEmpty || !agentOutput.isEmpty else { return }
        withAnimation(.spring(response: 0.3, dampingFraction: 0.82)) { showToast.toggle() }
        if showToast && mode == .result { scheduleAutoDismiss(after: timing.resultDismiss) }
        refreshPresentation()
    }

    private func scheduleIdleDismiss() {
        dismissTask?.cancel()
        guard autoHideEnabled else { return }
        dismissTask = Task { @MainActor in
            do { try await Task.sleep(nanoseconds: UInt64(timing.idleDismiss * 1_000_000_000)) }
            catch { return }
            guard autoHideEnabled, !isHoveringToast, mode == .idle, !showToast else { return }
            isManuallyPresented = false
            refreshPresentation()
        }
    }

    private func scheduleResetToIdle(after seconds: Double) {
        dismissTask?.cancel()
        dismissTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard mode == .cancelled else { return }
            withAnimation(.spring(response: 0.28, dampingFraction: 0.82)) {
                mode = .idle
                transcript = ""
                agentOutput = ""
            }
            refreshPresentation()
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
            guard mode != .speaking else { return }
            if case .recording = mode { return }
            stopQRPoll()
            isManuallyPresented = false
            withAnimation(.spring(response: 0.30, dampingFraction: 0.84)) {
                showToast = false
                if mode == .result {
                    mode = .idle
                }
                transcript = ""
                agentOutput = ""
            }
            refreshPresentation()
        }
    }
}
