import SwiftUI

public struct HUDView: View {
    @ObservedObject var appState: AppState
    @FocusState private var isInputFocused: Bool

    public init(appState: AppState) {
        self.appState = appState
    }

    public var body: some View {
        VStack(spacing: 0) {
            // Main Top Bar (Compact Pill / Header)
            HStack(spacing: 12) {
                // Bioluminescent Siri Acoustic Orb
                SiriOrbView(appState: appState, size: 34)
                    .frame(width: 40, height: 40)

                // Status or Live Transcription Text
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text("MAXI")
                            .font(.system(size: 11, weight: .black, design: .monospaced))
                            .foregroundColor(Color.cyan)

                        Circle()
                            .fill(statusDotColor)
                            .frame(width: 5, height: 5)

                        Text(statusTitle)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                    }

                    if !appState.currentTranscript.isEmpty {
                        Text(appState.currentTranscript)
                            .font(.system(size: 14, weight: .medium))
                            .foregroundColor(.primary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                    } else if appState.voiceState == .listening {
                        Text("Speak your command...")
                            .font(.system(size: 13, weight: .regular))
                            .foregroundColor(.secondary)
                    }
                }

                Spacer()

                // Action buttons / shortcuts
                HStack(spacing: 8) {
                    if !appState.currentResult.isEmpty {
                        Button(action: copyResult) {
                            Image(systemName: "doc.on.doc")
                                .font(.system(size: 11))
                                .foregroundColor(.secondary)
                                .padding(5)
                                .background(Color.white.opacity(0.08))
                                .clipShape(Circle())
                        }
                        .buttonStyle(.plain)
                        .help("Copy Response")
                    }

                    Button(action: { appState.hideHUD() }) {
                        Image(systemName: "xmark")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(.secondary)
                            .padding(5)
                            .background(Color.white.opacity(0.08))
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .help("Dismiss (ESC)")
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)

            // Expanded Card (Streamed Result & Tools Badges)
            if appState.isExpanded && (!appState.currentResult.isEmpty || !appState.toolsUsed.isEmpty) {
                Divider()
                    .background(Color.white.opacity(0.08))

                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        // MCP Tool invocation badges
                        if !appState.toolsUsed.isEmpty {
                            HStack(spacing: 6) {
                                ForEach(appState.toolsUsed, id: \.self) { tool in
                                    HStack(spacing: 4) {
                                        Image(systemName: "wrench.and.screwdriver.fill")
                                            .font(.system(size: 9))
                                        Text(tool.replacingOccurrences(of: "native-assistant-mcp:", with: ""))
                                            .font(.system(size: 10, weight: .medium, design: .monospaced))
                                    }
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 3)
                                    .background(Color.emeraldBadge.opacity(0.2))
                                    .foregroundColor(Color.emeraldBadge)
                                    .overlay(
                                        Capsule()
                                            .stroke(Color.emeraldBadge.opacity(0.4), lineWidth: 1)
                                    )
                                    .clipShape(Capsule())
                                }
                            }
                        }

                        // Streamed Text Output
                        if !appState.currentResult.isEmpty {
                            Text(appState.currentResult)
                                .font(.system(size: 13, weight: .regular))
                                .foregroundColor(.primary)
                                .textSelection(.enabled)
                                .lineSpacing(3)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
                .frame(maxHeight: 220)
            }

            // Quick Prompt Bar
            Divider()
                .background(Color.white.opacity(0.08))

            HStack(spacing: 8) {
                Image(systemName: "command")
                    .font(.system(size: 12))
                    .foregroundColor(Color.cyan.opacity(0.8))

                TextField("Type command or hold ⌥ to speak...", text: $appState.inputText)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12))
                    .focused($isInputFocused)
                    .onSubmit {
                        submitPrompt()
                    }

                if !appState.inputText.isEmpty {
                    Button(action: submitPrompt) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 15))
                            .foregroundColor(Color.cyan)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 9)
            .background(Color.black.opacity(0.2))
        }
        .frame(width: 480)
        .background(
            ZStack {
                // Frosted Liquid Glass Background
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(.ultraThinMaterial)

                // Dark tint for contrast
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(Color(red: 0.05, green: 0.07, blue: 0.12).opacity(0.7))

                // Hairline Specular Gradient Border
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(0.22),
                                Color.white.opacity(0.06),
                                Color.cyan.opacity(0.15)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
            }
        )
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: Color.black.opacity(0.4), radius: 25, x: 0, y: 12)
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: appState.isExpanded)
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: appState.voiceState)
    }

    private var statusTitle: String {
        switch appState.voiceState {
        case .listening: return "Listening (⌥ held)"
        case .processing: return "Thinking..."
        case .streaming: return "Streaming response"
        case .completed: return "Done"
        case .idle: return "Ready"
        }
    }

    private var statusDotColor: Color {
        switch appState.voiceState {
        case .listening: return Color.pink
        case .processing: return Color.orange
        case .streaming: return Color.cyan
        case .completed: return Color.green
        case .idle: return Color.secondary
        }
    }

    private func submitPrompt() {
        let text = appState.inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        appState.inputText = ""
        appState.isExpanded = true
        WebSocketClient.shared.sendPrompt(text: text)
    }

    private func copyResult() {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(appState.currentResult, forType: .string)
    }
}

extension Color {
    public static let emeraldBadge = Color(red: 0.06, green: 0.75, blue: 0.55)
}
