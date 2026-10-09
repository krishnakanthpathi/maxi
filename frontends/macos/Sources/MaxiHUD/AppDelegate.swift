import Cocoa
import SwiftUI

public final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var menu: NSMenu!
    private var statusMenuItem: NSMenuItem!
    private var modelMenuItem: NSMenuItem!
    private var toolsMenuItem: NSMenuItem!

    public func applicationDidFinishLaunching(_ notification: Notification) {
        // Setup Menu Bar Status Item
        setupStatusBar()

        // Initialize HUD Window Controller
        _ = HUDWindowController.shared

        // Start WebSocket connection to daemon
        WebSocketClient.shared.connect()

        // Observe AppState changes to update menu bar text dynamically
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(updateMenuState),
            name: .toggleMaxiHUD,
            object: nil
        )
    }

    private func setupStatusBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        if let button = statusItem.button {
            if let image = NSImage(systemSymbolName: "bolt.fill", accessibilityDescription: "Maxi") {
                image.isTemplate = true
                button.image = image
            } else {
                button.title = "⚡"
            }
            button.toolTip = "Maxi Assistant (Hold Right Option to Speak)"
        }

        buildMenu()
    }

    private func buildMenu() {
        menu = NSMenu()

        // Header
        let titleItem = NSMenuItem(title: "⚡ Maxi AI Workstation", action: nil, keyEquivalent: "")
        titleItem.isEnabled = false
        menu.addItem(titleItem)

        statusMenuItem = NSMenuItem(title: "Status: Connecting...", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        menu.addItem(statusMenuItem)

        modelMenuItem = NSMenuItem(title: "Model: gemma4:31b-cloud (Ollama)", action: nil, keyEquivalent: "")
        modelMenuItem.isEnabled = false
        menu.addItem(modelMenuItem)

        toolsMenuItem = NSMenuItem(title: "MCP Tools: 70 loaded", action: nil, keyEquivalent: "")
        toolsMenuItem.isEnabled = false
        menu.addItem(toolsMenuItem)

        menu.addItem(NSMenuItem.separator())

        // Primary actions
        let toggleItem = NSMenuItem(title: "Toggle HUD Panel", action: #selector(toggleHUDAction), keyEquivalent: "m")
        toggleItem.keyEquivalentModifierMask = [.command, .option]
        toggleItem.target = self
        menu.addItem(toggleItem)

        let webItem = NSMenuItem(title: "Open Web Workstation...", action: #selector(openWebConsole), keyEquivalent: "")
        webItem.target = self
        menu.addItem(webItem)

        menu.addItem(NSMenuItem.separator())

        // Sound audition & controls
        let soundMenu = NSMenu()
        for sound in ["minimal_wake", "glass_wake", "soft_wake", "scifi_wake", "zen_wake"] {
            let item = NSMenuItem(title: "Play \(sound)", action: #selector(auditionSound(_:)), keyEquivalent: "")
            item.representedObject = sound
            item.target = self
            soundMenu.addItem(item)
        }
        let soundSubmenu = NSMenuItem(title: "Audition Chimes", action: nil, keyEquivalent: "")
        soundSubmenu.submenu = soundMenu
        menu.addItem(soundSubmenu)

        let restartItem = NSMenuItem(title: "Restart Maxi Daemon", action: #selector(restartDaemon), keyEquivalent: "")
        restartItem.target = self
        menu.addItem(restartItem)

        menu.addItem(NSMenuItem.separator())

        // Quit
        let quitItem = NSMenuItem(title: "Quit Maxi HUD", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem.menu = menu

        // Periodic state check
        Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.updateMenuState()
        }
    }

    @objc private func updateMenuState() {
        Task { @MainActor in
            let state = AppState.shared
            self.statusMenuItem.title = "Status: \(state.connectionState.rawValue)"
            self.toolsMenuItem.title = "MCP Tools: \(state.loadedToolsCount) active"
        }
    }

    @objc private func toggleHUDAction() {
        Task { @MainActor in
            AppState.shared.toggleHUD()
        }
    }

    @objc private func openWebConsole() {
        if let url = URL(string: "http://127.0.0.1:4848/hud") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func auditionSound(_ sender: NSMenuItem) {
        guard let sound = sender.representedObject as? String else { return }
        let url = URL(string: "http://127.0.0.1:4848/api/sounds/play?name=\(sound)")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req).resume()
    }

    @objc private func restartDaemon() {
        let task = Process()
        let home = NSHomeDirectory()
        task.launchPath = "\(home)/.maxi/venv/bin/python3"
        task.arguments = ["-m", "app.cli", "restart"]
        task.currentDirectoryPath = "\(home)/Projects/maxi"
        try? task.run()
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}
