import SwiftUI

// Network and app-icon lookup are irrelevant to result-image handling.
@MainActor final class WebSocketClient {
    static let shared = WebSocketClient()
    func setAutoSpeech(enabled: Bool) {}
    func clearContext() {}
    func cancelActiveCommand() {}
    func stopTTS() {}
}
func getAppIcon(for name: String) -> NSImage? { nil }

@main struct ResultImageCheck {
    @MainActor static func main() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let imageURL = directory.appendingPathComponent("fresh QR.PNG")
        let bitmap = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2, bitsPerSample: 8,
            samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
            bytesPerRow: 0, bitsPerPixel: 0
        )!
        try bitmap.representation(using: .png, properties: [:])!.write(to: imageURL)

        let state = AppState()
        state.autoHideEnabled = false
        defer { state.stopQRPoll() }
        for tools in [["whatsapp_status", "whatsapp_login"], ["whatsapp_login"]] {
            state.handleResult(
                transcript: "Pair WhatsApp",
                output: "![WhatsApp QR Code](\(imageURL.absoluteString))",
                tools: tools, latencyMs: 10
            )
            precondition(state.qrFilePath == imageURL.path, "Must use the returned QR path")
            precondition(state.qrImage != nil, "QR image must load after status checks and login")
        }

        // A successful status check clears the old QR without loading a stale fallback.
        state.handleResult(
            transcript: "Check WhatsApp", output: "WhatsApp is linked.",
            tools: ["whatsapp_status"], latencyMs: 10
        )
        precondition(state.qrFilePath == nil && state.qrImage == nil)
        state.handleResult(
            transcript: "Link by code", output: "Use pairing code 1234-5678.",
            tools: ["whatsapp_login"], latencyMs: 10
        )
        precondition(state.qrFilePath == nil && state.qrImage == nil)
        precondition(ResultImage.path(in: "![QR](<\(imageURL.path)>)") == imageURL.path)
        precondition(ResultImage.path(in: "![QR](\(imageURL.absoluteString))") == imageURL.path)
        precondition(ResultImage.path(in: "QR code is at \(imageURL.path)") == nil)
        precondition(ResultImage.path(in: "![QR](https://example.com/qr.png)") == nil)
        precondition(ResultImage.path(in: "![QR](/missing/qr.png)") == nil)
        precondition(
            ResultImage.path(in: "![old](/missing/qr.png)\n![fresh](\(imageURL.path))") == imageURL.path
        )
    }
}
