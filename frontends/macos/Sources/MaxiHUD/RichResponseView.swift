import AppKit
import SwiftUI
import WebKit

enum MarkdownAssets {
    static var directory: URL {
        if let url = Bundle.main.resourceURL?.appendingPathComponent("Renderer"),
           FileManager.default.fileExists(atPath: url.appendingPathComponent("response.js").path) { return url }
        #if SWIFT_PACKAGE
        return Bundle.module.resourceURL!.appendingPathComponent("Renderer")
        #else
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Resources/Renderer")
        #endif
    }

    static func text(_ name: String) throws -> String {
        try String(contentsOf: directory.appendingPathComponent(name), encoding: .utf8)
    }
}

final class ScrollForwardingWebView: WKWebView {
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.modifierFlags.contains(.command) {
            let chars = event.charactersIgnoringModifiers?.lowercased()
            if chars == "c" {
                if NSApp.sendAction(#selector(NSText.copy(_:)), to: nil, from: self) {
                    return true
                }
            } else if chars == "a" {
                if NSApp.sendAction(#selector(NSText.selectAll(_:)), to: nil, from: self) {
                    return true
                }
            }
        }
        return super.performKeyEquivalent(with: event)
    }

    override func scrollWheel(with event: NSEvent) {
        // Allow horizontal scroll gestures to pass to WebKit for wide code blocks or tables.
        if abs(event.scrollingDeltaX) > abs(event.scrollingDeltaY) && event.scrollingDeltaX != 0 {
            super.scrollWheel(with: event)
            return
        }
        if let scrollView = enclosingScrollView {
            scrollView.scrollWheel(with: event)
        } else if let next = nextResponder {
            next.scrollWheel(with: event)
        } else {
            super.scrollWheel(with: event)
        }
    }
}

/// A transparent document inside the native scroll view; it only renders again
/// when response text changes, rather than on every speech/microphone update.
@MainActor
final class ResponseRenderer: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
    let webView: ScrollForwardingWebView
    var onHeight: (CGFloat) -> Void = { _ in }
    var onError: () -> Void = {}
    var onCopy: (String) -> Bool = { text in
        NSPasteboard.general.clearContents()
        return NSPasteboard.general.setString(text, forType: .string)
    }
    private var markdown: String?
    private var ready = false
    private(set) var loadError: Error?

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = ScrollForwardingWebView(frame: .zero, configuration: configuration)
        super.init()
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.underPageBackgroundColor = .clear
        let controller = webView.configuration.userContentController
        controller.add(self, name: "hud")
        do {
            let scripts = try ["marked.js", "purify.js", "highlight.js"].map(MarkdownAssets.text).joined(separator: "\n;\n")
            controller.addUserScript(WKUserScript(source: scripts,
                injectionTime: .atDocumentStart, forMainFrameOnly: true))
            let nonce = UUID().uuidString
            let css = try MarkdownAssets.text("response.css")
            let script = try MarkdownAssets.text("response.js").replacingOccurrences(of: "</script", with: "<\\/script")
            webView.loadHTMLString("""
            <!doctype html><html><head><meta charset="utf-8">
            <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src https: data:; frame-src about:; connect-src 'none'; base-uri 'none'; form-action 'none'">
            <style>\(css)</style></head><body><main id="response" aria-label="Markdown response"></main>
            <script nonce="\(nonce)">\(script)</script></body></html>
            """, baseURL: nil)
        } catch { loadError = error }
    }

    func render(_ source: String) {
        guard markdown != source else { return }
        markdown = source
        if loadError != nil { DispatchQueue.main.async { [weak self] in self?.onError() }; return }
        if ready { updateDocument() }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        ready = true
        updateDocument()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loadError = error
        onError()
    }

    private func updateDocument() {
        guard let markdown else { return }
        webView.callAsyncJavaScript("window.renderMarkdown(source)", arguments: ["source": markdown], in: nil, in: .page) { [weak self] result in
            if case .failure(let error) = result { self?.loadError = error; self?.onError() }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        // Preview frames never get access to the native clipboard or host bridge.
        guard message.frameInfo.isMainFrame, let body = message.body as? [String: Any] else { return }
        switch body["type"] as? String {
        case "height":
            if let height = body["height"] as? Double, height.isFinite, height > 0 {
                onHeight(CGFloat(min(height, 100_000)))
            }
        case "copy":
            guard let text = body["text"] as? String, text.utf8.count <= 1_000_000,
                  let id = body["id"] as? Int else { return }
            let success = onCopy(text)
            webView.callAsyncJavaScript("window.copyFinished(id, success)", arguments: ["id": id, "success": success], in: nil, in: .page, completionHandler: nil)
        default: break
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = navigationAction.request.url
        if navigationAction.navigationType == .linkActivated,
           navigationAction.sourceFrame.isMainFrame,
           let url, ["https", "http", "mailto"].contains(url.scheme?.lowercased() ?? "") {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        } else if navigationAction.targetFrame?.isMainFrame == false {
            // Do not let preview scripts navigate to a blank document and drop
            // their stricter CSP before writing new content into that frame.
            decisionHandler(url?.absoluteString == "about:srcdoc" ? .allow : .cancel)
        } else if url == nil || url?.absoluteString == "about:blank" {
            decisionHandler(.allow)
        } else { decisionHandler(.cancel) }
    }

    func dispose() {
        webView.stopLoading()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "hud")
        webView.navigationDelegate = nil
    }
}

private typealias ResponseViewState<Value> = SwiftUI.State<Value>

struct RichResponseView: View {
    let markdown: String
    @ResponseViewState private var height: CGFloat = 120
    @ResponseViewState private var failed = false

    var body: some View {
        if failed {
            Text(markdown).font(.system(size: 13)).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            MarkdownDocument(markdown: markdown, onHeight: { height = $0 }, onError: { failed = true })
                .frame(height: height)
        }
    }
}

private struct MarkdownDocument: NSViewRepresentable {
    let markdown: String
    let onHeight: (CGFloat) -> Void
    let onError: () -> Void

    func makeCoordinator() -> ResponseRenderer { ResponseRenderer() }
    func makeNSView(context: Context) -> ScrollForwardingWebView { context.coordinator.webView }
    func updateNSView(_ view: ScrollForwardingWebView, context: Context) {
        context.coordinator.onHeight = onHeight
        context.coordinator.onError = onError
        context.coordinator.render(markdown)
    }
    static func dismantleNSView(_ view: ScrollForwardingWebView, coordinator: ResponseRenderer) { coordinator.dispose() }
}
