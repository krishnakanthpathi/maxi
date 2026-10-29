import AppKit
import SwiftUI

private final class HUDHostingView<Content: View>: NSHostingView<Content> {
    // Custom SwiftUI buttons must accept the first click even while the user's
    // editor/browser remains the active application behind this panel.
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func hitTest(_ point: NSPoint) -> NSView? {
        // AppKit supplies the point in the superview's coordinates. SwiftUI's
        // hosting view is flipped, so using it directly rejects visible controls.
        let localPoint = convert(point, from: superview)
        let state = AppState.shared
        guard state.isPanelVisible else { return nil }
        let size = state.renderedSize
        let top = state.positionMode == .topNotch
        let y = isFlipped ? (top ? 0 : bounds.height - size.height - 16)
            : (top ? bounds.height - size.height : 16)
        let surface = NSRect(x: bounds.midX - size.width / 2, y: y, width: size.width, height: size.height)
        guard surface.contains(localPoint) else { return nil }
        let pointInStack = CGPoint(x: localPoint.x - surface.minX,
            y: isFlipped ? localPoint.y - surface.minY : surface.maxY - localPoint.y)
        guard HUDGeometry.hitSurface(pointInStack, size: size, pillSize: state.pillSize,
                                     atTop: top, hasResponse: state.showToast) else { return nil }
        return super.hitTest(point)
    }
}

final class BarPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func sendEvent(_ event: NSEvent) {
        if event.type == .leftMouseDown {
            if contentView?.hitTest(event.locationInWindow) != nil {
                if !NSApp.isActive {
                    NSApp.activate(ignoringOtherApps: true)
                }
                if !isKeyWindow {
                    makeKey()
                }
            }
        }
        super.sendEvent(event)
    }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.modifierFlags.contains(.command) {
            let chars = event.charactersIgnoringModifiers?.lowercased()
            if chars == "c" {
                if NSApp.sendAction(#selector(NSText.copy(_:)), to: nil, from: self) {
                    return true
                }
                let state = AppState.shared
                if !state.agentOutput.isEmpty {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(stripSpeechTag(from: state.agentOutput), forType: .string)
                    state.copiedFeedback = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { state.copiedFeedback = false }
                    return true
                } else if !state.transcript.isEmpty {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(state.transcript, forType: .string)
                    state.copiedPromptFeedback = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { state.copiedPromptFeedback = false }
                    return true
                }
            } else if chars == "a" {
                if NSApp.sendAction(#selector(NSText.selectAll(_:)), to: nil, from: self) {
                    return true
                }
            } else if chars == "v" {
                if NSApp.sendAction(#selector(NSText.paste(_:)), to: nil, from: self) {
                    return true
                }
            } else if chars == "x" {
                if NSApp.sendAction(#selector(NSText.cut(_:)), to: nil, from: self) {
                    return true
                }
            }
        }
        return super.performKeyEquivalent(with: event)
    }

    init<Content: View>(contentView: Content) {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 780, height: 600),
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
        self.becomesKeyOnlyIfNeeded = true

        let hostingView = HUDHostingView(rootView: contentView)
        hostingView.layer?.backgroundColor = NSColor.clear.cgColor
        self.contentView = hostingView
    }

    @MainActor
    func updatePosition() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let visibleFrame = screen.visibleFrame
        let fullFrame = screen.frame

        let panelWidth: CGFloat = min(fullFrame.width - 60, 780)
        let panelHeight: CGFloat = min(visibleFrame.height - 50, 600)
        let x = fullFrame.midX - (panelWidth / 2.0)
        let notchWidth: CGFloat
        if let left = screen.auxiliaryTopLeftArea, let right = screen.auxiliaryTopRightArea {
            notchWidth = max(160, fullFrame.width - left.width - right.width)
        } else {
            notchWidth = 180
        }
        let notchHeight = max(24, screen.safeAreaInsets.top)
        AppState.shared.updateNotch(width: notchWidth, height: notchHeight,
                                    bodyHeight: max(80, min(400, panelHeight - 140)))
        isMovableByWindowBackground = AppState.shared.positionMode == .bottomDock

        let y: CGFloat
        switch AppState.shared.positionMode {
        case .bottomDock:
            y = visibleFrame.minY + 14
        case .topNotch:
            // A separate pill floats below the menu bar/cutout and grows down.
            y = HUDGeometry.topEdge(fullFrame: fullFrame, visibleFrame: visibleFrame,
                                    safeTop: screen.safeAreaInsets.top) - panelHeight
        }

        let targetFrame = NSRect(x: x, y: y, width: panelWidth, height: panelHeight)
        self.setFrame(targetFrame, display: true, animate: false)
    }
}
