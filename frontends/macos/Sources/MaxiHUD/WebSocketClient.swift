import Foundation
import Combine

public final class WebSocketClient: NSObject {
    public static let shared = WebSocketClient()

    private var session: URLSession!
    private var webSocketTask: URLSessionWebSocketTask?
    private let url = URL(string: "ws://127.0.0.1:4848/ws")!
    private var isConnected = false
    private var reconnectAttempt = 0
    private var isIntentionalDisconnect = false
    private let queue = DispatchQueue(label: "com.maxi.websocket", qos: .userInitiated)

    private override init() {
        super.init()
        let config = URLSessionConfiguration.default
        self.session = URLSession(configuration: config, delegate: nil, delegateQueue: nil)
    }

    public func connect() {
        queue.async { [weak self] in
            guard let self = self else { return }
            self.isIntentionalDisconnect = false
            self.startConnection()
        }
    }

    public func disconnect() {
        queue.async { [weak self] in
            guard let self = self else { return }
            self.isIntentionalDisconnect = true
            self.webSocketTask?.cancel(with: .goingAway, reason: nil)
            self.webSocketTask = nil
            self.isConnected = false
            Task { @MainActor in
                AppState.shared.connectionState = .disconnected
            }
        }
    }

    private func startConnection() {
        webSocketTask?.cancel()
        
        Task { @MainActor in
            AppState.shared.connectionState = .connecting
        }

        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()
        
        // Ping daemon REST API once to verify port responsiveness and fetch PID/tools if needed
        verifyDaemonHealth()

        listenForMessages()
    }

    private func verifyDaemonHealth() {
        let healthUrl = URL(string: "http://127.0.0.1:4848/health")!
        let req = URLRequest(url: healthUrl, timeoutInterval: 2.0)
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            Task { @MainActor in
                if let pid = json["pid"] as? Int {
                    AppState.shared.daemonPID = pid
                }
                if let tools = json["tools_loaded"] as? Int {
                    AppState.shared.loadedToolsCount = tools
                }
            }
        }.resume()
    }

    private func listenForMessages() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }

            switch result {
            case .failure(let error):
                self.handleDisconnect(error: error)

            case .success(let message):
                self.handleMessage(message)
                self.listenForMessages()
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        if !isConnected {
            isConnected = true
            reconnectAttempt = 0
            Task { @MainActor in
                AppState.shared.connectionState = .connected
            }
        }

        let rawText: String?
        switch message {
        case .string(let text):
            rawText = text
        case .data(let data):
            rawText = String(data: data, encoding: .utf8)
        @unknown default:
            rawText = nil
        }

        guard let text = rawText,
              let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }

        Task { @MainActor in
            self.processEvent(json)
        }
    }

    @MainActor
    private func processEvent(_ json: [String: Any]) {
        let app = AppState.shared
        let event = json["event"] as? String ?? ""

        switch event {
        case "voice_start":
            app.setVoiceState(.listening)

        case "voice_interim_transcript":
            if let transcript = json["transcript"] as? String {
                app.currentTranscript = transcript
            }

        case "voice_stop":
            app.setVoiceState(.processing)

        case "voice_result":
            if let transcript = json["transcript"] as? String {
                app.currentTranscript = transcript
            }
            if let output = json["output"] as? String {
                app.currentResult = output
            }
            if let tools = json["tools"] as? [String] {
                app.toolsUsed = tools
            }
            app.setVoiceState(.completed)

        case "start":
            app.currentResult = ""
            app.toolsUsed = []
            app.setVoiceState(.streaming)

        case "chunk":
            let chunk = (json["data"] as? String) ?? (json["text"] as? String) ?? ""
            app.currentResult += chunk
            if app.voiceState != .streaming {
                app.setVoiceState(.streaming)
            }

        case "done", "complete":
            app.setVoiceState(.completed)

        default:
            break
        }
    }

    private func handleDisconnect(error: Error) {
        isConnected = false
        Task { @MainActor in
            AppState.shared.connectionState = .disconnected
        }

        guard !isIntentionalDisconnect else { return }

        // Exponential backoff reconnect: 1s, 2s, 3s, max 5s
        reconnectAttempt += 1
        let delay = min(Double(reconnectAttempt), 5.0)
        queue.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, !self.isIntentionalDisconnect else { return }
            self.startConnection()
        }
    }

    public func sendPrompt(text: String) {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }

        Task { @MainActor in
            AppState.shared.currentTranscript = text
            AppState.shared.currentResult = ""
            AppState.shared.toolsUsed = []
            AppState.shared.setVoiceState(.processing)
        }

        let payload: [String: Any] = [
            "type": "text_prompt",
            "text": text,
            "source": "macos:hud"
        ]

        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let jsonString = String(data: data, encoding: .utf8) else { return }

        let wsMsg = URLSessionWebSocketTask.Message.string(jsonString)
        webSocketTask?.send(wsMsg) { error in
            if let error = error {
                Task { @MainActor in
                    AppState.shared.currentResult = "Error communicating with Maxi daemon: \(error.localizedDescription)"
                    AppState.shared.setVoiceState(.completed)
                }
            }
        }
    }
}
