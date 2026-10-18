import Foundation

@MainActor
final class WebSocketClient {
    static let shared = WebSocketClient()

    private var webSocketTask: URLSessionWebSocketTask?
    private let session = URLSession(configuration: .default)
    private let wsURL = URL(string: "ws://127.0.0.1:4848/ws")!
    private let apiBase = URL(string: "http://127.0.0.1:4848/api")!
    private var isConnecting = false

    func start() {
        connect()
    }

    private func connect() {
        guard !isConnecting else { return }
        isConnecting = true

        webSocketTask?.cancel(with: .goingAway, reason: nil)
        let task = session.webSocketTask(with: wsURL)
        self.webSocketTask = task
        task.resume()

        receiveNext()
        sendPing()
    }

    private func receiveNext() {
        webSocketTask?.receive { [weak self] result in
            Task { @MainActor in
                guard let self = self else { return }
                switch result {
                case .success(let message):
                    self.isConnecting = false
                    AppState.shared.wsConnected = true
                    if case .string(let text) = message {
                        self.handlePayload(text)
                    }
                    self.receiveNext()
                case .failure:
                    self.isConnecting = false
                    AppState.shared.wsConnected = false
                    self.scheduleReconnect()
                }
            }
        }
    }

    private func sendPing() {
        webSocketTask?.sendPing { [weak self] error in
            Task { @MainActor in
                guard let self = self else { return }
                if error == nil {
                    AppState.shared.wsConnected = true
                    try? await Task.sleep(nanoseconds: 10_000_000_000)
                    self.sendPing()
                } else {
                    AppState.shared.wsConnected = false
                    self.scheduleReconnect()
                }
            }
        }
    }

    private func scheduleReconnect() {
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            self.connect()
        }
    }

    private func handlePayload(_ jsonText: String) {
        guard let data = jsonText.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let event = obj["event"] as? String else {
            return
        }

        let state = AppState.shared
        switch event {
        case "voice_start":
            let locked = (obj["locked"] as? Bool) ?? false
            state.handleVoiceStart(locked: locked)

        case "voice_lock":
            let locked = (obj["locked"] as? Bool) ?? true
            state.handleVoiceLock(locked: locked)

        case "voice_context":
            if let ctx = obj["context"] as? [String: Any] {
                let info = CapturedContextInfo(
                    appName: (ctx["app_name"] as? String) ?? "",
                    bundleId: (ctx["bundle_id"] as? String) ?? "",
                    windowTitle: (ctx["window_title"] as? String) ?? "",
                    url: (ctx["url"] as? String) ?? "",
                    selectedText: (ctx["selected_text"] as? String) ?? ""
                )
                state.handleContextUpdate(info)
            }

        case "audio_level":
            let levels = (obj["levels"] as? [Double]) ?? [0.15, 0.2, 0.25, 0.2, 0.15]
            let locked = (obj["locked"] as? Bool) ?? false
            let elapsed = (obj["elapsed"] as? Double) ?? 0.0
            state.handleAudioLevels(levels, locked: locked, elapsed: elapsed)

        case "voice_stop":
            let cancelled = (obj["cancelled"] as? Bool) ?? false
            let reason = (obj["reason"] as? String) ?? "release"
            state.handleVoiceStop(cancelled: cancelled, reason: reason)

        case "voice_processing":
            state.handleProcessing()

        case "tool_start":
            let tool = (obj["tool"] as? String) ?? ""
            state.handleToolStart(tool)

        case "tool_end":
            let tool = (obj["tool"] as? String) ?? ""
            state.handleToolEnd(tool)

        case "voice_transcript":
            let transcript = (obj["transcript"] as? String) ?? ""
            state.handleTranscript(transcript)

        case "voice_result":
            let transcript = (obj["transcript"] as? String) ?? ""
            let output = (obj["output"] as? String) ?? ""
            let tools = (obj["tools"] as? [String]) ?? []
            let latency = Int((obj["latency_ms"] as? Double) ?? Double((obj["latency_ms"] as? Int) ?? 0))
            state.handleResult(transcript: transcript, output: output, tools: tools, latencyMs: latency)

        case "tts_start":
            state.handleTTSStart()

        case "tts_stop":
            state.handleTTSStop()

        case "voice_idle":
            state.handleVoiceIdle()

        default:
            break
        }
    }

    func stopTTS() {
        var req = URLRequest(url: apiBase.appendingPathComponent("tts/stop"))
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req).resume()
    }

    func injectTextAtCursor(_ text: String) {
        guard !text.isEmpty else { return }
        var req = URLRequest(url: apiBase.appendingPathComponent("inject"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["text": text, "preserve_clipboard": true]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req).resume()
    }
}
