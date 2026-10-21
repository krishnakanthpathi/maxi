import SwiftUI
import AppKit

func getAppIcon(for appName: String) -> NSImage? {
    let clean = appName.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !clean.isEmpty else { return nil }
    if let running = NSWorkspace.shared.runningApplications.first(where: {
        $0.localizedName?.caseInsensitiveCompare(clean) == .orderedSame
    }), let icon = running.icon {
        return icon
    }
    if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: clean) {
        return NSWorkspace.shared.icon(forFile: url.path)
    }
    return nil
}

struct FiveBandWaveformView: View {
    let levels: [CGFloat]
    let accentColor: Color
    let isAnimated: Bool

    var body: some View {
        HStack(spacing: 3.5) {
            ForEach(0..<min(levels.count, 5), id: \.self) { idx in
                let raw = levels[idx]
                let height = max(4.0, min(20.0, raw * 20.0))
                Capsule(style: .continuous)
                    .fill(accentColor)
                    .frame(width: 3.2, height: isAnimated ? height : 4.5)
                    .animation(isAnimated ? .interactiveSpring(response: 0.08, dampingFraction: 0.62) : nil, value: height)
            }
        }
        .frame(height: 20)
    }
}

func stripSpeechTag(from text: String) -> String {
    var result = text
    let speechPattern = #"<speech>[\s\S]*?</speech>"#
    if let regex = try? NSRegularExpression(pattern: speechPattern, options: .caseInsensitive) {
        let nsString = result as NSString
        let range = NSRange(location: 0, length: nsString.length)
        result = regex.stringByReplacingMatches(in: result, options: [], range: range, withTemplate: "")
    }
    let imgPattern = #"!\[.*?\]\([^\)]+\)"#
    if let regex = try? NSRegularExpression(pattern: imgPattern, options: .caseInsensitive) {
        let nsString = result as NSString
        let range = NSRange(location: 0, length: nsString.length)
        result = regex.stringByReplacingMatches(in: result, options: [], range: range, withTemplate: "")
    }
    return result.trimmingCharacters(in: .whitespacesAndNewlines)
}

func formatArgSummary(_ args: [String: Any]) -> String? {
    guard !args.isEmpty else { return nil }
    if let msg = args["message"] as? String, !msg.isEmpty {
        let trimmed = msg.replacingOccurrences(of: "\n", with: " ")
        return trimmed.count > 26 ? String(trimmed.prefix(23)) + "..." : trimmed
    }
    if let r = args["recipient"] as? String, !r.isEmpty {
        return r
    }
    if let q = args["query"] as? String, !q.isEmpty {
        let trimmed = q.replacingOccurrences(of: "\n", with: " ")
        return trimmed.count > 22 ? String(trimmed.prefix(19)) + "..." : trimmed
    }
    if let app = args["appName"] as? String ?? args["application"] as? String, !app.isEmpty {
        return app
    }
    if let p = args["path"] as? String, !p.isEmpty {
        return (p as NSString).lastPathComponent
    }
    return nil
}

struct ToastCardView: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: "sum")
                    .font(.system(size: 14, weight: .semibold))
                    .accessibilityLabel("Maxi summation logo")
                Text("Maxi")
                    .font(.system(size: 13, weight: .semibold))
                Spacer()

                Button(action: { state.clearContext() }) {
                    controlIcon(state.contextClearedFeedback ? "checkmark" : "plus")
                }
                .buttonStyle(HUDButtonStyle(isSelected: state.contextClearedFeedback))
                .accessibilityLabel("New chat")
                .help(state.contextClearedFeedback ? "New chat started" : "New chat · Clear recent conversation")

                Button(action: { state.toggleAutoHide() }) {
                    controlIcon(state.autoHideEnabled ? "pin" : "pin.fill")
                }
                .buttonStyle(HUDButtonStyle(isSelected: !state.autoHideEnabled))
                .accessibilityLabel(state.autoHideEnabled ? "Pin response" : "Unpin response")
                .help(state.autoHideEnabled ? "Keep this response visible" : "Allow response to auto-dismiss")

                Button(action: { state.toggleAutoSpeech() }) {
                    controlIcon(state.autoSpeechEnabled ? "speaker.wave.2" : "speaker.slash")
                }
                .buttonStyle(HUDButtonStyle(isSelected: state.autoSpeechEnabled))
                .accessibilityLabel(state.autoSpeechEnabled ? "Mute speech" : "Enable speech")
                .help(state.autoSpeechEnabled ? "Mute speech" : "Enable speech")

                Button(action: { state.dismissToast() }) {
                    controlIcon("xmark")
                }
                .buttonStyle(HUDButtonStyle())
                .accessibilityLabel("Dismiss response")
                .help("Dismiss response")
            }

            HStack(alignment: .top, spacing: 10) {
                Text(state.transcript.isEmpty ? "Listening…" : state.transcript)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)

                if !state.transcript.isEmpty {
                    Button(action: {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(state.transcript, forType: .string)
                        state.copiedPromptFeedback = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { state.copiedPromptFeedback = false }
                    }) {
                        controlIcon(state.copiedPromptFeedback ? "checkmark" : "doc.on.clipboard")
                    }
                    .buttonStyle(HUDButtonStyle(isSelected: state.copiedPromptFeedback))
                    .accessibilityLabel("Copy prompt")
                    .help(state.copiedPromptFeedback ? "Prompt copied" : "Copy prompt")
                }
            }

            if let img = state.qrImage {
                VStack(spacing: 10) {
                    Image(nsImage: img)
                        .resizable()
                        .interpolation(.none)
                        .scaledToFit()
                        .frame(width: 175, height: 175)
                        .padding(10)
                        .background(.white, in: RoundedRectangle(cornerRadius: 16))
                        .accessibilityLabel("WhatsApp pairing QR code")

                    Label("Linked Devices · Refreshes in \(state.qrCountdown)s", systemImage: "arrow.clockwise")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
            } else if state.qrFilePath != nil {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Loading pairing QR code…")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            }

            if !state.toolsUsed.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(Array(state.toolsUsed.enumerated()), id: \.offset) { _, tool in
                            Label(tool.replacingOccurrences(of: "_", with: " "), systemImage: "checkmark")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 9)
                                .padding(.vertical, 5)
                                .background(Color.primary.opacity(0.05), in: Capsule())
                        }
                    }
                }
            }

            if !state.agentOutput.isEmpty {
                Divider()

                ScrollView(.vertical) {
                    Text(LocalizedStringKey(stripSpeechTag(from: state.agentOutput)))
                        .font(.system(size: 13))
                        .foregroundStyle(.primary)
                        .lineSpacing(4)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: state.qrImage == nil ? 220 : 100)

                HStack(spacing: 10) {
                    if state.latencyMs > 0 {
                        Label("\(Double(state.latencyMs) / 1000.0, specifier: "%.1f")s", systemImage: "clock")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                    if !state.autoSpeechEnabled {
                        Image(systemName: "speaker.slash")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .accessibilityLabel("Speech muted")
                    }
                    Spacer()

                    if state.mode == .speaking {
                        Button(action: {
                            WebSocketClient.shared.stopTTS()
                            state.handleTTSStop()
                        }) {
                            Label("Stop Voice", systemImage: "stop.fill")
                                .font(.system(size: 11, weight: .medium))
                                .padding(.horizontal, 10)
                                .frame(height: 28)
                        }
                        .buttonStyle(HUDButtonStyle())
                    }

                    Button(action: {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(stripSpeechTag(from: state.agentOutput), forType: .string)
                        state.copiedFeedback = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { state.copiedFeedback = false }
                    }) {
                        Label(state.copiedFeedback ? "Copied" : "Copy", systemImage: state.copiedFeedback ? "checkmark" : "doc.on.doc")
                            .font(.system(size: 11, weight: .medium))
                            .padding(.horizontal, 10)
                            .frame(height: 28)
                    }
                    .buttonStyle(HUDButtonStyle(isSelected: state.copiedFeedback))
                    .accessibilityLabel("Copy response")
                }
            }
        }
        .padding(18)
        .frame(maxWidth: 540)
        .maxiGlass(in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .onHover { state.setHovering($0) }
    }

    private func controlIcon(_ symbol: String) -> some View {
        Image(systemName: symbol)
            .font(.system(size: 14, weight: .medium))
            .frame(width: 28, height: 28)
    }
}

struct MaxiPillBarView: View {
    @ObservedObject var state: AppState

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var statusText: String {
        switch state.mode {
        case .idle:
            return state.wsConnected ? "Hold ⌥ to speak" : "Connecting..."
        case .recording(let locked):
            let secs = Int(state.elapsedSeconds)
            let formatted = String(format: "%d:%02d", secs / 60, secs % 60)
            return locked ? "Locked \(formatted)" : formatted
        case .processing:
            if let tool = state.currentExecutingTool {
                return tool.replacingOccurrences(of: "_", with: " ")
            }
            return "Thinking..."
        case .speaking:
            return "Speaking..."
        case .result:
            return "Done"
        case .cancelled:
            return "Cancelled"
        }
    }

    private var isRecordingOrSpeaking: Bool {
        switch state.mode {
        case .recording, .speaking:
            return true
        default:
            return false
        }
    }

    var body: some View {
        HStack(spacing: 8.5) {
            // Compact status indicator
            switch state.mode {
            case .idle:
                Image(systemName: state.wsConnected ? "sum" : "antenna.radiowaves.left.and.right")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .frame(width: 14, height: 14)
            case .recording(let locked):
                if locked {
                    Image(systemName: "lock.fill")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.primary)
                        .frame(width: 14, height: 14)
                }
            case .processing:
                Group {
                    if state.currentExecutingTool != nil {
                        Image(systemName: "terminal.fill")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(.primary)
                    } else {
                        ProgressView()
                            .controlSize(.mini)
                    }
                }
                .frame(width: 14, height: 14)
            case .speaking:
                Image(systemName: "waveform")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.primary)
                    .frame(width: 14, height: 14)
            case .result:
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.primary)
                    .frame(width: 14, height: 14)
            case .cancelled:
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.secondary)
                    .frame(width: 14, height: 14)
            }

            // Show the app icon directly, without a surrounding badge.
            if case .recording = state.mode {
                if let icon = state.activeAppIcon ?? (state.contextInfo.appName.isEmpty ? nil : getAppIcon(for: state.contextInfo.appName)) {
                    HStack(spacing: 3) {
                        Image(nsImage: icon)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 20, height: 20)

                        if state.contextInfo.hasSelection {
                            Circle()
                                .fill(Color.primary.opacity(0.75))
                                .frame(width: 4, height: 4)
                        }
                    }
                }
            }

            // Live audio levels
            if isRecordingOrSpeaking {
                FiveBandWaveformView(
                    levels: state.audioLevels,
                    accentColor: .primary,
                    isAnimated: !reduceMotion
                )
            }

            // Tool Execution pill (no reload/spinner symbol, no steps)
            if state.mode == .processing, let tool = state.currentExecutingTool {
                HStack(spacing: 6) {
                    // Tool Name (Full, Unhidden, Monospaced)
                    Text(tool.replacingOccurrences(of: "_", with: " "))
                        .font(.system(size: 11.5, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.primary)
                        .lineLimit(1)

                    // Key Argument summary preview if available
                    if let argSummary = formatArgSummary(state.currentToolArgs) {
                        Text(argSummary)
                            .font(.system(size: 10.5, weight: .regular, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(
                    Capsule()
                        .fill(Color.primary.opacity(0.06))
                        .overlay(
                            Capsule()
                                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5)
                        )
                )
            } else {
                // Status / Hint label
                Text(statusText)
                    .font(.system(size: 11.5, weight: .semibold, design: .rounded))
                    .foregroundStyle(state.mode == .idle ? Color.secondary : Color.primary)
                    .lineLimit(1)
            }

            // Quick speech status toggle button
            Button(action: {
                state.toggleAutoSpeech()
            }) {
                Image(systemName: state.autoSpeechEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                    .font(.system(size: 13, weight: .medium))
                    .frame(width: 26, height: 26)
            }
            .buttonStyle(HUDButtonStyle())
            .accessibilityLabel(state.autoSpeechEnabled ? "Mute speech" : "Enable speech")
            .help(state.autoSpeechEnabled ? "Auto-Speech active (click to mute)" : "Auto-Speech muted (click to unmute)")
        }
        .padding(.leading, 16)
        .padding(.trailing, 7)
        .padding(.vertical, 7)
        .maxiGlass(in: Capsule(style: .continuous), interactive: true)
        .contentShape(Capsule())
        .onTapGesture {
            if state.mode == .speaking {
                WebSocketClient.shared.stopTTS()
                state.handleTTSStop()
            } else if !state.agentOutput.isEmpty || !state.transcript.isEmpty {
                withAnimation(.spring(response: 0.28, dampingFraction: 0.8)) {
                    state.showToast.toggle()
                }
            }
        }
        .contextMenu {
            Button(action: { state.clearContext() }) {
                Label("New Chat", systemImage: "plus")
            }
            Divider()
            Button(action: { state.toggleAutoHide() }) {
                if state.autoHideEnabled {
                    Label("Auto-Hide Results: Enabled", systemImage: "checkmark")
                } else {
                    Label("Auto-Hide Results: Disabled (Pinned)", systemImage: "pin.fill")
                }
            }
            Button(action: { state.toggleAutoSpeech() }) {
                if state.autoSpeechEnabled {
                    Label("Auto-Speech (Read Aloud): Enabled", systemImage: "checkmark")
                } else {
                    Label("Auto-Speech (Read Aloud): Disabled", systemImage: "speaker.slash")
                }
            }
            Divider()
            Button("Position: Bottom Dock") {
                state.setPosition(.bottomDock)
            }
            Button("Position: Top Notch") {
                state.setPosition(.topNotch)
            }
            Button(state.alwaysShowIdlePill ? "Hide Idle Pill" : "Always Show Idle Pill") {
                state.alwaysShowIdlePill.toggle()
                state.onLayoutChange?()
            }
        }
    }
}

typealias WillowPillBarView = MaxiPillBarView

struct HUDView: View {
    @ObservedObject var state = AppState.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HUDGlassGroup {
            VStack(spacing: 14) {
                if state.positionMode == .bottomDock {
                    Spacer(minLength: 0)
                    if state.showToast {
                        ToastCardView(state: state)
                            .transition(.asymmetric(
                                insertion: reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity),
                                removal: reduceMotion ? .opacity : .opacity.combined(with: .scale(scale: 0.96))
                            ))
                    }
                    if state.isHUDVisible {
                        MaxiPillBarView(state: state)
                    }
                } else {
                    if state.isHUDVisible {
                        MaxiPillBarView(state: state)
                    }
                    if state.showToast {
                        ToastCardView(state: state)
                            .transition(.asymmetric(
                                insertion: reduceMotion ? .opacity : .move(edge: .top).combined(with: .opacity),
                                removal: reduceMotion ? .opacity : .opacity.combined(with: .scale(scale: 0.96))
                            ))
                    }
                    Spacer(minLength: 0)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)
            .padding(.bottom, 12)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: state.positionMode == .bottomDock ? .bottom : .top)
        }
        .transaction { transaction in
            if reduceMotion { transaction.animation = nil }
        }
    }
}
