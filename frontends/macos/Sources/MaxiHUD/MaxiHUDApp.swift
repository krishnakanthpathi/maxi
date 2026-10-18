import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var panel: BarPanel?
    private var statusItem: NSStatusItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let hudView = HUDView(state: AppState.shared)
        let barPanel = BarPanel(contentView: hudView)
        barPanel.updatePosition()
        self.panel = barPanel
        syncPanelVisibility()

        AppState.shared.onLayoutChange = { [weak self] in
            self?.syncPanelVisibility()
        }

        setupStatusBarMenu()
        WebSocketClient.shared.start()

        // Global and local Escape monitoring to immediately close toast pop-up and stop TTS
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53 { // Escape key
                if AppState.shared.showToast || AppState.shared.mode == .speaking {
                    AppState.shared.dismissToast()
                    return nil
                }
            }
            return event
        }

        NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53 {
                Task { @MainActor in
                    if AppState.shared.showToast || AppState.shared.mode == .speaking {
                        AppState.shared.dismissToast()
                    }
                }
            }
        }

        NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.syncPanelVisibility()
            }
        }
    }

    private func syncPanelVisibility() {
        guard let panel = self.panel else { return }
        if AppState.shared.isHUDVisible {
            panel.updatePosition()
            panel.orderFrontRegardless()
        } else {
            panel.orderOut(nil)
        }
    }

    private func setupStatusBarMenu() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = item.button {
            button.image = NSImage(systemSymbolName: "waveform.circle.fill", accessibilityDescription: "Maxi HUD")
        }

        let menu = NSMenu()

        let titleItem = NSMenuItem(title: "⚡ Maxi HUD", action: nil, keyEquivalent: "")
        titleItem.isEnabled = false
        menu.addItem(titleItem)
        menu.addItem(NSMenuItem.separator())

        let bottomItem = NSMenuItem(title: "Position: Bottom Dock", action: #selector(setBottomDock), keyEquivalent: "")
        bottomItem.target = self
        menu.addItem(bottomItem)

        let topItem = NSMenuItem(title: "Position: Top Notch", action: #selector(setTopNotch), keyEquivalent: "")
        topItem.target = self
        menu.addItem(topItem)

        let toggleIdleItem = NSMenuItem(title: "Toggle Idle Pill Visibility", action: #selector(toggleIdlePill), keyEquivalent: "")
        toggleIdleItem.target = self
        menu.addItem(toggleIdleItem)

        let showLastItem = NSMenuItem(title: "Show Last Transcript Toast", action: #selector(showLastToast), keyEquivalent: "")
        showLastItem.target = self
        menu.addItem(showLastItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Quit Maxi HUD", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        item.menu = menu
        self.statusItem = item
    }

    @objc private func setBottomDock() {
        AppState.shared.setPosition(.bottomDock)
    }

    @objc private func setTopNotch() {
        AppState.shared.setPosition(.topNotch)
    }

    @objc private func toggleIdlePill() {
        AppState.shared.alwaysShowIdlePill.toggle()
        syncPanelVisibility()
    }

    @objc private func showLastToast() {
        AppState.shared.showToast = true
        syncPanelVisibility()
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}

@main
struct MaxiHUDMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
