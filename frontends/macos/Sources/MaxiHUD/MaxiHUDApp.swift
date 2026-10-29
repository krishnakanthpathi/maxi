import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, NSMenuItemValidation {
    private var panel: BarPanel?
    private var statusItem: NSStatusItem?

    private var autoSpeechMenuItem: NSMenuItem?
    private var autoHideMenuItem: NSMenuItem?
    private var bottomDockMenuItem: NSMenuItem?
    private var topNotchMenuItem: NSMenuItem?
    private var toggleIdleItem: NSMenuItem?
    private var modelParentItem: NSMenuItem?
    private var modelSubmenu: NSMenu?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let hudView = HUDView(state: AppState.shared)
        let barPanel = BarPanel(contentView: hudView)
        barPanel.updatePosition()
        self.panel = barPanel

        AppState.shared.onLayoutChange = { [weak self] in
            self?.syncPanelVisibility()
        }

        setupMainMenu()
        setupStatusBarMenu()
        AppState.shared.revealHUD()
        BackendBootstrap.start { WebSocketClient.shared.start() }

        // Global and local Escape monitoring to immediately cancel active voice command, STT, LLM, or toast
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53 { // Escape key
                if AppState.shared.isHUDVisible {
                    AppState.shared.handleEscape()
                    return nil
                }
            }
            return event
        }

        NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53 {
                Task { @MainActor in
                    if AppState.shared.isHUDVisible {
                        AppState.shared.handleEscape()
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

        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                WebSocketClient.shared.reconnect()
                self?.syncPanelVisibility()
            }
        }

        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.activeSpaceDidChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.syncPanelVisibility()
            }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        AppState.shared.revealHUD()
        if panel != nil && !AppState.shared.wsConnected {
            BackendBootstrap.start { WebSocketClient.shared.start() }
        }
        return true
    }

    private func syncPanelVisibility() {
        guard let panel = self.panel else { return }
        if AppState.shared.isPanelVisible {
            panel.updatePosition()
            panel.orderFrontRegardless()
        } else {
            panel.orderOut(nil)
        }
    }

    private func setupMainMenu() {
        guard NSApp.mainMenu == nil else { return }
        let mainMenu = NSMenu()

        // App Menu
        let appMenuItem = NSMenuItem(title: "Maxi", action: nil, keyEquivalent: "")
        let appMenu = NSMenu(title: "Maxi")
        appMenu.addItem(withTitle: "About Maxi", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Quit Maxi", action: #selector(quitApp), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        // Edit Menu (Enables standard Cmd+C, Cmd+V, Cmd+A, Cmd+X shortcuts across the app)
        let editMenuItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        NSApp.mainMenu = mainMenu
    }

    private func setupStatusBarMenu() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = item.button {
            button.image = NSImage(systemSymbolName: "sum", accessibilityDescription: "Maxi")
            button.image?.isTemplate = true
        }

        let menu = NSMenu()
        menu.delegate = self

        let titleItem = NSMenuItem(title: "∑ Maxi", action: nil, keyEquivalent: "")
        titleItem.isEnabled = false
        menu.addItem(titleItem)
        menu.addItem(NSMenuItem.separator())

        let showItem = NSMenuItem(title: "Show Maxi", action: #selector(showMaxi), keyEquivalent: "0")
        showItem.target = self
        menu.addItem(showItem)

        // Active Model Selection Submenu
        let modelParent = NSMenuItem(title: "🤖 Model: \(AppState.shared.currentModel)", action: nil, keyEquivalent: "")
        let modelMenu = NSMenu()
        modelParent.submenu = modelMenu
        menu.addItem(modelParent)
        self.modelParentItem = modelParent
        self.modelSubmenu = modelMenu
        rebuildModelMenu()
        WebSocketClient.shared.fetchAvailableModels { [weak self] _ in
            self?.rebuildModelMenu()
        }

        // Skills & MCP Configuration Submenu
        let toolsParent = NSMenuItem(title: "🧩 Skills & MCP Servers", action: nil, keyEquivalent: "")
        let toolsMenu = NSMenu()

        let openSkillsItem = NSMenuItem(title: "📂 Open Skills Folder (~/.maxi/skills)", action: #selector(openSkillsFolder), keyEquivalent: "")
        openSkillsItem.target = self
        toolsMenu.addItem(openSkillsItem)

        let openMCPItem = NSMenuItem(title: "⚙️ Edit MCP Config (~/.maxi/mcp_config.json)", action: #selector(openMCPConfig), keyEquivalent: "")
        openMCPItem.target = self
        toolsMenu.addItem(openMCPItem)

        let openEnvItem = NSMenuItem(title: "📝 Edit Environment Config (~/.maxi/.env)", action: #selector(openEnvConfig), keyEquivalent: "")
        openEnvItem.target = self
        toolsMenu.addItem(openEnvItem)

        let reloadToolsItem = NSMenuItem(title: "🔄 Reload Skills & MCP Servers", action: #selector(reloadSkillsAndMCP), keyEquivalent: "r")
        reloadToolsItem.target = self
        toolsMenu.addItem(reloadToolsItem)

        toolsParent.submenu = toolsMenu
        menu.addItem(toolsParent)

        menu.addItem(NSMenuItem.separator())

        // Auto-speech toggle option
        let speechItem = NSMenuItem(
            title: "Auto-Speech (Read Aloud)",
            action: #selector(toggleAutoSpeech),
            keyEquivalent: "s"
        )
        speechItem.target = self
        speechItem.state = AppState.shared.autoSpeechEnabled ? .on : .off
        menu.addItem(speechItem)
        self.autoSpeechMenuItem = speechItem

        // Auto-hide toggle option (pin without closing)
        let autoHideItem = NSMenuItem(
            title: "Auto-hide Responses",
            action: #selector(toggleAutoHide),
            keyEquivalent: "h"
        )
        autoHideItem.target = self
        autoHideItem.state = AppState.shared.autoHideEnabled ? .on : .off
        menu.addItem(autoHideItem)
        self.autoHideMenuItem = autoHideItem

        menu.addItem(NSMenuItem.separator())

        let bottomItem = NSMenuItem(title: "Position: Bottom Dock", action: #selector(setBottomDock), keyEquivalent: "")
        bottomItem.target = self
        bottomItem.state = AppState.shared.positionMode == .bottomDock ? .on : .off
        menu.addItem(bottomItem)
        self.bottomDockMenuItem = bottomItem

        let topItem = NSMenuItem(title: "Position: Below Notch", action: #selector(setTopNotch), keyEquivalent: "")
        topItem.target = self
        topItem.state = AppState.shared.positionMode == .topNotch ? .on : .off
        menu.addItem(topItem)
        self.topNotchMenuItem = topItem

        let idleItem = NSMenuItem(title: "Always Show Idle Pill", action: #selector(toggleIdlePill), keyEquivalent: "")
        idleItem.target = self
        idleItem.state = AppState.shared.alwaysShowIdlePill ? .on : .off
        menu.addItem(idleItem)
        self.toggleIdleItem = idleItem


        // Start a fresh conversation without deleting saved memories.
        let clearItem = NSMenuItem(
            title: "New Chat",
            action: #selector(clearContext),
            keyEquivalent: "k"
        )
        clearItem.target = self
        menu.addItem(clearItem)

        let showLastItem = NSMenuItem(title: "Show Last Transcript Toast", action: #selector(showLastToast), keyEquivalent: "")
        showLastItem.target = self
        menu.addItem(showLastItem)

        let openEnvMainItem = NSMenuItem(title: "📝 Edit .env Config (~/.maxi/.env)", action: #selector(openEnvConfig), keyEquivalent: "e")
        openEnvMainItem.target = self
        menu.addItem(openEnvMainItem)

        let reloadMainItem = NSMenuItem(title: "🔄 Reload Configuration", action: #selector(reloadConfigAction), keyEquivalent: "r")
        reloadMainItem.target = self
        menu.addItem(reloadMainItem)

        let restartMainItem = NSMenuItem(title: "⚡ Restart Maxi Daemon", action: #selector(restartMaxiAction), keyEquivalent: "")
        restartMainItem.target = self
        menu.addItem(restartMainItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Quit Maxi HUD", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        item.menu = menu
        self.statusItem = item
    }

    func menuWillOpen(_ menu: NSMenu) {
        WebSocketClient.shared.syncConfig()
        WebSocketClient.shared.fetchAvailableModels { [weak self] _ in
            self?.rebuildModelMenu()
        }
        modelParentItem?.title = "🤖 Model: \(AppState.shared.currentModel)"
        rebuildModelMenu()

        autoSpeechMenuItem?.state = AppState.shared.autoSpeechEnabled ? .on : .off
        autoHideMenuItem?.state = AppState.shared.autoHideEnabled ? .on : .off
        bottomDockMenuItem?.state = AppState.shared.positionMode == .bottomDock ? .on : .off
        topNotchMenuItem?.state = AppState.shared.positionMode == .topNotch ? .on : .off
        toggleIdleItem?.state = AppState.shared.alwaysShowIdlePill ? .on : .off
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        let backendActions: [Selector] = [#selector(clearContext), #selector(toggleAutoSpeech),
            #selector(selectModel(_:)), #selector(promptCustomModel), #selector(refreshModelsAction),
            #selector(reloadSkillsAndMCP)]
        if let action = menuItem.action, backendActions.contains(action) {
            return AppState.shared.wsConnected
        }
        return true
    }

    private func rebuildModelMenu() {
        guard let menu = self.modelSubmenu else { return }
        menu.removeAllItems()

        let current = AppState.shared.currentModel.lowercased()
        for model in AppState.shared.availableModels {
            let item = NSMenuItem(title: model, action: #selector(selectModel(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = model
            item.state = (model.lowercased() == current) ? .on : .off
            menu.addItem(item)
        }

        menu.addItem(NSMenuItem.separator())
        let refreshItem = NSMenuItem(title: "🔄 Refresh Models from Endpoint", action: #selector(refreshModelsAction), keyEquivalent: "")
        refreshItem.target = self
        menu.addItem(refreshItem)

        let customItem = NSMenuItem(title: "Custom Model Name...", action: #selector(promptCustomModel), keyEquivalent: "")
        customItem.target = self
        menu.addItem(customItem)
    }

    @objc private func refreshModelsAction() {
        WebSocketClient.shared.fetchAvailableModels { [weak self] _ in
            Task { @MainActor in
                self?.rebuildModelMenu()
            }
        }
    }

    @objc private func selectModel(_ sender: NSMenuItem) {
        guard let model = sender.representedObject as? String else { return }
        WebSocketClient.shared.setModel(model) { [weak self] in
            Task { @MainActor in
                self?.rebuildModelMenu()
            }
        }
    }

    @objc private func promptCustomModel() {
        guard AppState.shared.wsConnected else { return }
        let alert = NSAlert()
        alert.messageText = "Set Custom Model Name"
        alert.informativeText = "Enter any Ollama, Groq, or OpenAI-compatible model identifier:"
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Set Model")
        alert.addButton(withTitle: "Cancel")

        let input = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
        input.stringValue = AppState.shared.currentModel
        alert.accessoryView = input

        if alert.runModal() == .alertFirstButtonReturn {
            let model = input.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if !model.isEmpty {
                if !AppState.shared.availableModels.contains(model) {
                    AppState.shared.availableModels.append(model)
                }
                WebSocketClient.shared.setModel(model) { [weak self] in
                    Task { @MainActor in
                        self?.rebuildModelMenu()
                    }
                }
            }
        }
    }

    @objc private func openSkillsFolder() {
        let path = NSString(string: "~/.maxi/skills").expandingTildeInPath
        NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: path)
    }

    @objc private func openMCPConfig() {
        let path = NSString(string: "~/.maxi/mcp_config.json").expandingTildeInPath
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    @objc private func openEnvConfig() {
        AppState.shared.openEnvConfig()
    }

    @objc private func reloadSkillsAndMCP() {
        AppState.shared.reloadConfig()
    }

    @objc private func reloadConfigAction() {
        AppState.shared.reloadConfig()
    }

    @objc private func restartMaxiAction() {
        AppState.shared.restartMaxi()
    }

    @objc private func toggleAutoSpeech() {
        AppState.shared.toggleAutoSpeech()
        autoSpeechMenuItem?.state = AppState.shared.autoSpeechEnabled ? .on : .off
    }

    @objc private func toggleAutoHide() {
        AppState.shared.toggleAutoHide()
        autoHideMenuItem?.state = AppState.shared.autoHideEnabled ? .on : .off
    }

    @objc private func setBottomDock() {
        AppState.shared.setPosition(.bottomDock)
    }

    @objc private func setTopNotch() {
        AppState.shared.setPosition(.topNotch)
    }

    @objc private func toggleIdlePill() {
        AppState.shared.setAlwaysShowIdle(!AppState.shared.alwaysShowIdlePill)
    }


    @objc private func showMaxi() {
        AppState.shared.revealHUD()
    }

    @objc private func showLastToast() {
        AppState.shared.showToast = true
        AppState.shared.revealHUD()
    }

    @objc private func clearContext() {
        AppState.shared.clearContext()
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}

#if !MAXI_HUD_TESTING
@main
struct MaxiHUDMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
#endif
