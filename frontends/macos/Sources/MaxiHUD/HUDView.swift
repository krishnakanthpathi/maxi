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
                    .animation(.interactiveSpring(response: 0.08, dampingFraction: 0.62), value: height)
            }
        }
        .frame(height: 20)
    }
}

struct ToastCardView: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header row: User transcript + Close button
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "sparkles")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color(red: 0.38, green: 0.85, blue: 0.98))
                    .padding(.top, 2)

                Text(state.transcript.isEmpty ? "Listening..." : state.transcript)
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(.white.opacity(0.88))
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Button(action: { state.dismissToast() }) {
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.white.opacity(0.55))
                        .frame(width: 18, height: 18)
                        .background(Circle().fill(.white.opacity(0.08)))
                }
                .buttonStyle(.plain)
            }

            // Real-time & completed tool execution badges
            if !state.toolsUsed.isEmpty || state.currentExecutingTool != nil {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 5) {
                        ForEach(state.toolsUsed, id: \.self) { tool in
                            let isRunning = state.currentExecutingTool == tool
                            HStack(spacing: 3.5) {
                                Image(systemName: isRunning ? "arrow.triangle.2.circlepath" : "bolt.fill")
                                    .font(.system(size: 8))
                                Text(tool)
                                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            }
                            .foregroundStyle(isRunning ? Color(red: 0.40, green: 0.88, blue: 1.0) : Color(red: 0.65, green: 0.92, blue: 0.75))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2.5)
                            .background(
                                Capsule()
                                    .fill(isRunning ? Color(red: 0.12, green: 0.28, blue: 0.45).opacity(0.75) : Color(red: 0.16, green: 0.36, blue: 0.26).opacity(0.65))
                                    .overlay(
                                        Capsule()
                                            .strokeBorder(isRunning ? Color(red: 0.40, green: 0.88, blue: 1.0).opacity(0.4) : Color.clear, lineWidth: 0.8)
                                    )
                            )
                        }
                    }
                }
            }

            if !state.agentOutput.isEmpty {
                Divider()
                    .overlay(.white.opacity(0.10))

                ScrollView(.vertical, showsIndicators: true) {
                    Text(state.agentOutput)
                        .font(.system(size: 12.5, weight: .regular))
                        .foregroundStyle(.white.opacity(0.95))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 115)

                // Footer actions: Latency + Stop Voice (if speaking) + Copy
                HStack(spacing: 8) {
                    if state.latencyMs > 0 {
                        Text("\(Double(state.latencyMs) / 1000.0, specifier: "%.1f")s")
                            .font(.system(size: 10, weight: .medium, design: .monospaced))
                            .foregroundStyle(.white.opacity(0.42))
                    }

                    Spacer()

                    if state.mode == .speaking {
                        Button(action: {
                            WebSocketClient.shared.stopTTS()
                            state.handleTTSStop()
                        }) {
                            Label("Stop Voice", systemImage: "speaker.slash.fill")
                                .font(.system(size: 10.5, weight: .semibold))
                                .foregroundStyle(Color(red: 1.0, green: 0.55, blue: 0.55))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3.5)
                                .background(Capsule().fill(.white.opacity(0.09)))
                        }
                        .buttonStyle(.plain)
                    }

                    Button(action: {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(state.agentOutput, forType: .string)
                        state.copiedFeedback = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { state.copiedFeedback = false }
                    }) {
                        Label(state.copiedFeedback ? "Copied" : "Copy", systemImage: state.copiedFeedback ? "checkmark" : "doc.on.doc")
                            .font(.system(size: 10.5, weight: .semibold))
                            .foregroundStyle(.white.opacity(0.85))
                            .padding(.horizontal, 9)
                            .padding(.vertical, 4)
                            .background(Capsule().fill(.white.opacity(0.08)))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .frame(width: 410)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(red: 0.06, green: 0.06, blue: 0.08).opacity(0.94))
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .strokeBorder(
                            LinearGradient(
                                colors: [
                                    .white.opacity(0.22),
                                    .white.opacity(0.06)
                                ],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            ),
                            lineWidth: 1
                        )
                )
                .shadow(color: .black.opacity(0.45), radius: 16, x: 0, y: 8)
        )
        .onHover { hovering in
            state.setHovering(hovering)
        }
    }
}

struct MaxiPillBarView: View {
    @ObservedObject var state: AppState

    private var accentColor: Color {
        switch state.mode {
        case .idle:
            return state.wsConnected ? Color.white.opacity(0.45) : Color.orange.opacity(0.7)
        case .recording(let locked):
            return locked
                ? Color(red: 1.0, green: 0.72, blue: 0.22) // Amber for hands-free lock
                : Color(red: 0.22, green: 0.92, blue: 0.68) // Emerald-cyan for push-to-talk
        case .processing:
            return state.currentExecutingTool != nil
                ? Color(red: 0.38, green: 0.82, blue: 1.0) // Bright cyan for real-time tool
                : Color.white.opacity(0.70) // Subtle white for clean thinking
        case .speaking:
            return Color(red: 0.75, green: 0.48, blue: 1.0) // Violet
        case .result:
            return Color(red: 0.28, green: 0.88, blue: 0.65)
        case .cancelled:
            return Color(red: 0.98, green: 0.42, blue: 0.42)
        }
    }

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
                return "\(tool)..."
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

    // Audio level waveform is strictly for live recording or speaking audio
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
            // Left state icon
            switch state.mode {
            case .idle:
                Circle()
                    .fill(state.wsConnected ? Color(red: 0.25, green: 0.90, blue: 0.62) : Color.orange)
                    .frame(width: 7, height: 7)
                    .frame(width: 14, height: 14)
            case .recording(let locked):
                if locked {
                    Image(systemName: "lock.fill")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(accentColor)
                        .frame(width: 14, height: 14)
                }
            case .processing:
                Group {
                    if state.currentExecutingTool != nil {
                        Image(systemName: "bolt.fill")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(accentColor)
                    } else {
                        ProgressView()
                            .controlSize(.mini)
                    }
                }
                .frame(width: 14, height: 14)
            case .speaking:
                Image(systemName: "waveform")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(accentColor)
                    .frame(width: 14, height: 14)
            case .result:
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(accentColor)
                    .frame(width: 14, height: 14)
            case .cancelled:
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(accentColor)
                    .frame(width: 14, height: 14)
            }

            // Detected App Icon badge in recording section
            if case .recording = state.mode {
                if let icon = state.activeAppIcon ?? (state.contextInfo.appName.isEmpty ? nil : getAppIcon(for: state.contextInfo.appName)) {
                    HStack(spacing: 3) {
                        Image(nsImage: icon)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 14, height: 14)
                            .clipShape(RoundedRectangle(cornerRadius: 3.5, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 3.5, style: .continuous)
                                    .strokeBorder(Color.white.opacity(0.18), lineWidth: 0.5)
                            )

                        if state.contextInfo.hasSelection {
                            Circle()
                                .fill(Color(red: 0.22, green: 0.92, blue: 0.68))
                                .frame(width: 4, height: 4)
                        }
                    }
                    .padding(.horizontal, 4.5)
                    .padding(.vertical, 2.5)
                    .background(Capsule().fill(.white.opacity(0.08)))
                }
            }

            // 5-band audio level visualizer (only during audio recording or speaking)
            if isRecordingOrSpeaking {
                FiveBandWaveformView(
                    levels: state.audioLevels,
                    accentColor: accentColor,
                    isAnimated: true
                )
            }

            // Real-time Tool Calling badge during processing
            if state.mode == .processing, let tool = state.currentExecutingTool {
                HStack(spacing: 4) {
                    Image(systemName: "gearshape.2.fill")
                        .font(.system(size: 9))
                    Text(tool)
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                }
                .foregroundStyle(Color(red: 0.45, green: 0.88, blue: 1.0))
                .padding(.horizontal, 7)
                .padding(.vertical, 2.5)
                .background(
                    Capsule()
                        .fill(Color(red: 0.12, green: 0.26, blue: 0.40).opacity(0.75))
                        .overlay(
                            Capsule()
                                .strokeBorder(Color(red: 0.38, green: 0.82, blue: 1.0).opacity(0.4), lineWidth: 0.8)
                        )
                )
            } else {
                // Status / Hint label
                Text(statusText)
                    .font(.system(size: 11.5, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(state.mode == .idle ? 0.72 : 0.95))
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 7.5)
        .background(
            Capsule(style: .continuous)
                .fill(Color(red: 0.05, green: 0.05, blue: 0.07).opacity(0.92))
                .overlay(
                    Capsule(style: .continuous)
                        .strokeBorder(accentColor.opacity(state.mode == .idle ? 0.22 : 0.65), lineWidth: 1.1)
                )
                .shadow(color: .black.opacity(0.42), radius: 10, x: 0, y: 4)
        )
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
    }
}

typealias WillowPillBarView = MaxiPillBarView

struct HUDView: View {
    @ObservedObject var state = AppState.shared

    var body: some View {
        VStack(spacing: 10) {
            if state.positionMode == .bottomDock {
                Spacer(minLength: 0)
                if state.showToast {
                    ToastCardView(state: state)
                        .transition(.asymmetric(
                            insertion: .move(edge: .bottom).combined(with: .opacity),
                            removal: .opacity.combined(with: .scale(scale: 0.96))
                        ))
                }
                if state.alwaysShowIdlePill || state.mode != .idle || state.showToast {
                    MaxiPillBarView(state: state)
                }
            } else {
                if state.alwaysShowIdlePill || state.mode != .idle || state.showToast {
                    MaxiPillBarView(state: state)
                }
                if state.showToast {
                    ToastCardView(state: state)
                        .transition(.asymmetric(
                            insertion: .move(edge: .top).combined(with: .opacity),
                            removal: .opacity.combined(with: .scale(scale: 0.96))
                        ))
                }
                Spacer(minLength: 0)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .frame(width: 460, height: 320)
    }
}
