import AppKit
import SwiftUI

final class BarPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    init<Content: View>(contentView: Content) {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 320),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        self.isFloatingPanel = true
        self.level = .statusBar + 1
        self.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
            .ignoresCycle
        ]
        self.backgroundColor = .clear
        self.isOpaque = false
        self.hasShadow = false
        self.isMovableByWindowBackground = true
        self.hidesOnDeactivate = false

        let hostingView = NSHostingView(rootView: contentView)
        hostingView.layer?.backgroundColor = NSColor.clear.cgColor
        self.contentView = hostingView
    }

    @MainActor
    func updatePosition() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let visibleFrame = screen.visibleFrame
        let fullFrame = screen.frame

        let panelWidth: CGFloat = 460
        let panelHeight: CGFloat = 320
        let x = fullFrame.midX - (panelWidth / 2.0)

        let y: CGFloat
        switch AppState.shared.positionMode {
        case .bottomDock:
            y = visibleFrame.minY + 14
        case .topNotch:
            y = visibleFrame.maxY - panelHeight - 8
        }

        let targetFrame = NSRect(x: x, y: y, width: panelWidth, height: panelHeight)
        self.setFrame(targetFrame, display: true, animate: false)
    }
}
