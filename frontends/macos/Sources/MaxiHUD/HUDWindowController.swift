import Cocoa
import SwiftUI

public final class HUDWindowController: NSWindowController {
    public static let shared = HUDWindowController()

    private var panel: NSPanel!
    private var localEventMonitor: Any?

    private init() {
        let hudView = HUDView(appState: AppState.shared)
        let hostingView = NSHostingView(rootView: hudView)

        let initialRect = NSRect(x: 0, y: 0, width: 480, height: 64)
        let panel = NSPanel(
            contentRect: initialRect,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        panel.contentView = hostingView
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.isMovableByWindowBackground = true
        panel.hidesOnDeactivate = false
        panel.alphaValue = 0.0

        super.init(window: panel)
        self.panel = panel

        setupObservers()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private func setupObservers() {
        NotificationCenter.default.addObserver(
            forName: .toggleMaxiHUD,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let self = self else { return }
            if let shouldShow = note.object as? Bool {
                if shouldShow {
                    self.showHUD()
                } else {
                    self.hideHUD()
                }
            } else {
                self.toggleHUD()
            }
        }

        // Global ESC key listener to dismiss HUD
        localEventMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self else { return event }
            if event.keyCode == 53 && self.panel.isVisible && self.panel.alphaValue > 0.1 { // ESC key
                self.hideHUD()
                return nil
            }
            return event
        }
    }

    public func showHUD() {
        positionPanel()
        panel.orderFrontRegardless()

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.22
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().alphaValue = 1.0
        }
    }

    public func hideHUD() {
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.18
            context.timingFunction = CAMediaTimingFunction(name: .easeIn)
            panel.animator().alphaValue = 0.0
        }, completionHandler: {
            self.panel.orderOut(nil)
        })
    }

    public func toggleHUD() {
        if panel.isVisible && panel.alphaValue > 0.5 {
            hideHUD()
        } else {
            showHUD()
        }
    }

    private func positionPanel() {
        guard let screen = NSScreen.main else { return }
        let screenRect = screen.visibleFrame
        let panelWidth: CGFloat = 480
        let panelHeight: CGFloat = panel.contentView?.fittingSize.height ?? 100

        // Position bottom-center, ~70pt above Dock/bottom
        let posX = screenRect.origin.x + (screenRect.width - panelWidth) / 2
        let posY = screenRect.origin.y + 70

        panel.setFrame(NSRect(x: posX, y: posY, width: panelWidth, height: panelHeight), display: true)
    }

    deinit {
        if let monitor = localEventMonitor {
            NSEvent.removeMonitor(monitor)
        }
    }
}
