import Foundation

@MainActor
final class WebSocketClient {
    static let shared = WebSocketClient()

    private var webSocketTask: URLSessionWebSocketTask?
    private let session = URLSession(configuration: .default)
    private let wsURL: URL
    private let apiBase: URL
    private let reconnectDelay: UInt64
    private let heartbeatInterval: UInt64
    private let heartbeatTimeout: UInt64
    private var isRunning = false
    private var reconnectTask: Task<Void, Never>?
    private var heartbeatTask: Task<Void, Never>?
    private var heartbeatTimeoutTask: Task<Void, Never>?

    init(
        wsURL: URL = URL(string: "ws://127.0.0.1:4848/ws")!,
        apiBase: URL = URL(string: "http://127.0.0.1:4848/api")!,
        reconnectDelay: UInt64 = 1_500_000_000,
        heartbeatInterval: UInt64 = 5_000_000_000,
        heartbeatTimeout: UInt64 = 5_000_000_000
    ) {
        self.wsURL = wsURL
        self.apiBase = apiBase
        self.reconnectDelay = reconnectDelay
        self.heartbeatInterval = heartbeatInterval
        self.heartbeatTimeout = heartbeatTimeout
    }

    func start() {
        guard !isRunning else { return }
        isRunning = true
        connect()
    }

    func stop() {
        isRunning = false
        cancelConnectionWork()
        let oldTask = webSocketTask
        webSocketTask = nil
        oldTask?.cancel(with: .goingAway, reason: nil)
        AppState.shared.wsConnected = false
    }

    func reconnect() {
        guard isRunning else { return }
        connect()
    }

    private func cancelConnectionWork() {
        reconnectTask?.cancel()
        reconnectTask = nil
        heartbeatTask?.cancel()
        heartbeatTask = nil
        heartbeatTimeoutTask?.cancel()
        heartbeatTimeoutTask = nil
    }

    private func connect() {
        guard isRunning else { return }
        cancelConnectionWork()
        let oldTask = webSocketTask
        webSocketTask = nil
        oldTask?.cancel(with: .goingAway, reason: nil)
        AppState.shared.wsConnected = false

        let task = session.webSocketTask(with: wsURL)
        webSocketTask = task
        task.resume()
        syncTTSState()
        syncConfig()
        receiveNext(from: task)
        sendPing(on: task)
    }

    private func receiveNext(from task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor in
                // Cancellation callbacks from an old socket must never change
                // the new socket's state or start another receive/retry loop.
                guard let self, self.webSocketTask === task else { return }
                switch result {
                case .success(let message):
                    AppState.shared.wsConnected = true
                    if case .string(let text) = message {
                        self.handlePayload(text)
                    }
                    self.receiveNext(from: task)
                case .failure(let error):
                    self.connectionFailed(task, reason: error.localizedDescription)
                }
            }
        }
    }

    private func sendPing(on task: URLSessionWebSocketTask) {
        guard isRunning, webSocketTask === task else { return }
        heartbeatTimeoutTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await Task.sleep(nanoseconds: self.heartbeatTimeout)
            } catch { return }
            self.connectionFailed(task, reason: "Heartbeat timed out")
        }
        task.sendPing { [weak self] error in
            Task { @MainActor in
                guard let self, self.webSocketTask === task else { return }
                self.heartbeatTimeoutTask?.cancel()
                self.heartbeatTimeoutTask = nil
                if let error {
                    self.connectionFailed(task, reason: error.localizedDescription)
                    return
                }
                if !AppState.shared.wsConnected {
                    NSLog("[MaxiHUD] Connected to voice daemon")
                }
                AppState.shared.wsConnected = true
                self.heartbeatTask = Task { [weak self] in
                    guard let self else { return }
                    do {
                        try await Task.sleep(nanoseconds: self.heartbeatInterval)
                    } catch { return }
                    self.sendPing(on: task)
                }
            }
        }
    }

    private func connectionFailed(_ task: URLSessionWebSocketTask, reason: String) {
        guard isRunning, webSocketTask === task else { return }
        // Clear identity before cancelling, since both receive and ping may fail.
        webSocketTask = nil
        cancelConnectionWork()
        task.cancel(with: .goingAway, reason: nil)
        AppState.shared.wsConnected = false
        NSLog("[MaxiHUD] Voice connection lost: %@. Reconnecting…", reason)
        reconnectTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await Task.sleep(nanoseconds: self.reconnectDelay)
            } catch { return }
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
            let args = (obj["args"] as? [String: Any]) ?? [:]
            state.handleToolStart(tool, args: args)

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

        case "hud_dismiss":
            state.dismissToast()

        default:
            break
        }
    }

    func cancelActiveCommand() {
        var req = URLRequest(url: apiBase.appendingPathComponent("voice/cancel"))
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req).resume()
    }

    func clearContext(completion: (() -> Void)? = nil) {
        var req = URLRequest(url: apiBase.appendingPathComponent("context/clear"))
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req) { _, _, _ in
            completion?()
        }.resume()
    }

    func stopTTS() {
        var req = URLRequest(url: apiBase.appendingPathComponent("tts/stop"))
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req).resume()
    }

    func setAutoSpeech(enabled: Bool) {
        var req = URLRequest(url: apiBase.appendingPathComponent("config"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["enable_tts": enabled ? "true" : "false"]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req).resume()
    }

    func syncTTSState() {
        let req = URLRequest(url: apiBase.appendingPathComponent("tts"))
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let active = json["active"] as? [String: Any],
                  let enabled = active["enable_tts"] as? Bool else { return }
            Task { @MainActor in
                AppState.shared.autoSpeechEnabled = enabled
                UserDefaults.standard.set(enabled, forKey: "maxi.hud.auto_speech")
            }
        }.resume()
    }

    func syncConfig() {
        let req = URLRequest(url: apiBase.appendingPathComponent("config"))
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let config = json["config"] as? [String: Any],
                  let model = config["llm_model"] as? String else { return }
            Task { @MainActor in
                AppState.shared.currentModel = model
            }
        }.resume()
    }

    func fetchAvailableModels(completion: (([String]) -> Void)? = nil) {
        let req = URLRequest(url: apiBase.appendingPathComponent("models"))
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let models = json["models"] as? [String] else {
                completion?([])
                return
            }
            let current = json["current_model"] as? String
            Task { @MainActor in
                if !models.isEmpty {
                    AppState.shared.availableModels = models
                }
                if let current = current, !current.isEmpty {
                    AppState.shared.currentModel = current
                }
                completion?(models)
            }
        }.resume()
    }

    func setModel(_ modelName: String, completion: (() -> Void)? = nil) {
        var req = URLRequest(url: apiBase.appendingPathComponent("config"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["model": modelName]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { _, _, _ in
            Task { @MainActor in
                AppState.shared.currentModel = modelName
                completion?()
            }
        }.resume()
    }

    func reloadDaemon(completion: (() -> Void)? = nil) {
        var req = URLRequest(url: apiBase.appendingPathComponent("reload"))
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req) { _, _, _ in
            Task { @MainActor in
                completion?()
            }
        }.resume()
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
