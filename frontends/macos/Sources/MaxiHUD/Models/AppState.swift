import Foundation
import SwiftUI
import Combine

public enum DaemonConnectionState: String {
    case connecting = "Connecting..."
    case connected = "Connected"
    case disconnected = "Offline"
}

public enum VoiceState: String {
    case idle = "Idle"
    case listening = "Listening..."
    case processing = "Thinking..."
    case streaming = "Responding..."
    case completed = "Done"
}

@MainActor
public final class AppState: ObservableObject {
    public static let shared = AppState()

    @Published public var connectionState: DaemonConnectionState = .connecting
    @Published public var voiceState: VoiceState = .idle
    @Published public var currentTranscript: String = ""
    @Published public var currentResult: String = ""
    @Published public var toolsUsed: [String] = []
    @Published public var isHUDVisible: Bool = false
    @Published public var inputText: String = ""
    @Published public var isExpanded: Bool = false
    @Published public var lastActiveTimestamp: Date = Date()
    @Published public var daemonPID: Int? = nil
    @Published public var loadedToolsCount: Int = 70

    private var autoDismissTask: Task<Void, Never>? = nil

    private init() {}

    public func setVoiceState(_ newState: VoiceState) {
        self.voiceState = newState
        self.lastActiveTimestamp = Date()
        
        switch newState {
        case .listening:
            self.autoDismissTask?.cancel()
            self.autoDismissTask = nil
            self.currentTranscript = ""
            self.currentResult = ""
            self.toolsUsed = []
            self.isExpanded = false
            self.showHUD()

        case .processing:
            self.autoDismissTask?.cancel()
            self.autoDismissTask = nil
            self.showHUD()

        case .streaming:
            self.autoDismissTask?.cancel()
            self.autoDismissTask = nil
            self.isExpanded = true
            self.showHUD()

        case .completed:
            self.isExpanded = !self.currentResult.isEmpty || !self.toolsUsed.isEmpty
            self.scheduleAutoDismiss(afterSeconds: 6)

        case .idle:
            break
        }
    }

    public func showHUD() {
        self.isHUDVisible = true
        NotificationCenter.default.post(name: .toggleMaxiHUD, object: true)
    }

    public func hideHUD() {
        self.autoDismissTask?.cancel()
        self.autoDismissTask = nil
        self.isHUDVisible = false
        NotificationCenter.default.post(name: .toggleMaxiHUD, object: false)
    }

    public func toggleHUD() {
        if isHUDVisible {
            hideHUD()
        } else {
            showHUD()
        }
    }

    public func scheduleAutoDismiss(afterSeconds: Double = 6.0) {
        self.autoDismissTask?.cancel()
        self.autoDismissTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(afterSeconds * 1_000_000_000))
            if !Task.isCancelled && self.voiceState != .listening && self.voiceState != .processing {
                withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
                    self.hideHUD()
                }
            }
        }
    }

    public func clearSession() {
        self.currentTranscript = ""
        self.currentResult = ""
        self.toolsUsed = []
        self.isExpanded = false
        self.inputText = ""
        self.voiceState = .idle
    }
}

extension Notification.Name {
    public static let toggleMaxiHUD = Notification.Name("MaxiHUD.ToggleWindow")
}
