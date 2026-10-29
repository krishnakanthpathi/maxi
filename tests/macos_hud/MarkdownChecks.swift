import AppKit
import WebKit

@main
@MainActor
struct MarkdownChecks {
    static func main() {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)
        Task { @MainActor in
            do { try await run(); NSApp.terminate(nil) }
            catch { fatalError("Markdown checks failed: \(error)") }
        }
        NSApp.run()
    }

    static func waitUntil(_ label: String, _ predicate: () async throws -> Bool) async throws {
        let deadline = Date().addingTimeInterval(8)
        while Date() < deadline {
            if try await predicate() { return }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        preconditionFailure(label)
    }

    static func check(_ renderer: ResponseRenderer, _ expression: String, _ label: String) async throws {
        let result = try await renderer.webView.evaluateJavaScript(expression)
        precondition(result as? Bool == true, label)
    }

    static func run() async throws {
        let renderer = ResponseRenderer()
        defer { renderer.dispose() }
        var height: CGFloat = 0
        var copies: [String] = []
        renderer.onHeight = { height = $0 }
        renderer.onCopy = { copies.append($0); return true }
        renderer.onError = { fatalError("Renderer error: \(String(describing: renderer.loadError))") }
        let window = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 504, height: 440),
                             styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = renderer.webView
        // DOM sizing and rendering must also work without a visible test panel.
        window.orderOut(nil)
        defer { window.orderOut(nil) }
        let markdown = """
        # Markdown response
        **Bold**, *italic*, ~~removed~~, `inline`, [a link](https://example.com).

        > A quote

        - [x] Finished
        - [ ] Next

        1. First
        2. Second

        | Feature | Status |
        | :--- | ---: |
        | Tables | Ready |

        ```python
        print("hello <world>")
        ```

        ```html
        <button id="counter" onclick="this.textContent = 'Count: 1'">Count: 0</button>
        <script>window.webkit?.messageHandlers?.hud?.postMessage({type:'copy',text:'frame must not copy',id:99}); window.top.postMessage('preview-ready', '*')</script>
        ```

        <details><summary>More</summary>Extra details</details>
        <script>window.parentInjected = true</script>
        <img src="invalid:test" onerror="window.parentInjected = true">
        <a href="javascript:window.parentInjected=true">Bad link</a>
        """
        renderer.render(markdown)
        try await waitUntil("Markdown never rendered") { height > 100 }
        try await check(renderer, "document.querySelector('h1').textContent === 'Markdown response'", "Missing heading")
        try await check(renderer, "document.querySelectorAll('table th').length === 2 && document.querySelector('table td').textContent === 'Tables'", "GFM tables missing")
        try await check(renderer, "getComputedStyle(document.querySelectorAll('table th')[1]).textAlign === 'right'", "Table column alignment missing")
        try await check(renderer, "document.querySelectorAll('input[type=checkbox]').length === 2 && document.querySelector('input').checked && document.querySelector('input').disabled", "Task lists missing")
        try await check(renderer, "!!document.querySelector('del') && !!document.querySelector('ol') && !!document.querySelector('blockquote') && !!document.querySelector('details summary')", "Markdown block formatting missing")
        try await check(renderer, "document.querySelectorAll('.code-block').length === 2 && !!document.querySelector('.hljs-string')", "Fenced code/highlighting missing")
        try await check(renderer, "!window.parentInjected && !document.querySelector('#response script') && !document.querySelector('[onerror]') && !document.querySelector('a[href^=javascript]')", "Response HTML escaped sanitization")
        print("PASS: headings, GFM tables/tasks, lists, quotes, details, syntax highlighting and sanitization")

        // Exercise the real document handlers and native message bridge without
        // touching the user's clipboard or sending any backend requests.
        _ = try await renderer.webView.evaluateJavaScript("document.querySelector('button[aria-label=\"Copy code\"]').click()")
        try await waitUntil("Code copy did not reach the native handler") { copies.count == 1 }
        precondition(copies[0] == "print(\"hello <world>\")\n", "Copy altered the code")
        try await waitUntil("Code copy did not show confirmation") {
            try await renderer.webView.evaluateJavaScript("!!document.querySelector('button[aria-label=\"Code copied\"]')") as? Bool == true
        }
        print("PASS: per-block copy preserves exact code and confirms native clipboard success")

        _ = try await renderer.webView.evaluateJavaScript("window.previewMessages=[]; addEventListener('message', event => window.previewMessages.push(event.data)); document.querySelector('button[aria-label=\"Preview HTML\"]').click()")
        try await waitUntil("HTML preview scripts did not run") {
            try await renderer.webView.evaluateJavaScript("window.previewMessages.includes('preview-ready')") as? Bool == true
        }
        try await check(renderer, "document.querySelector('iframe').sandbox.value === 'allow-scripts' && document.querySelector('iframe').srcdoc.includes(\"connect-src 'none'\")", "Preview isolation missing")
        try await check(renderer, "document.querySelector('iframe').srcdoc.includes('Count: 0') && document.querySelector('button[aria-expanded=true]').textContent === 'Code'", "HTML preview controls missing")
        precondition(copies.count == 1, "Preview frame reached the native clipboard bridge")
        let expandedHeight = height
        _ = try await renderer.webView.evaluateJavaScript("document.querySelector('button[aria-label=\"Show HTML code\"]').click()")
        try await waitUntil("Preview height did not contract") { height < expandedHeight }
        print("PASS: HTML previews execute locally, remain isolated and resize the response")

        renderer.render("<!doctype html><html><body><h1>Standalone HTML</h1></body></html>")
        try await waitUntil("Standalone HTML was not detected") {
            try await renderer.webView.evaluateJavaScript("!!document.querySelector('button[aria-label=\"Preview HTML\"]') && document.querySelector('code').textContent.includes('Standalone HTML')") as? Bool == true
        }
        renderer.render("Short replacement")
        try await waitUntil("Response update left stale code or preview content") {
            try await renderer.webView.evaluateJavaScript("document.getElementById('response').textContent.trim() === 'Short replacement' && !document.querySelector('iframe')") as? Bool == true
        }
        print("PASS: standalone HTML gets preview controls; updates discard old previews and code")
    }
}
