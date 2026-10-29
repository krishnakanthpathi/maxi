import AppKit
import SwiftUI

// Keep the same surface hierarchy on macOS 14/15 while using the system's
// Liquid Glass renderer when it is available.
private struct GlassSurface<Surface: InsettableShape>: ViewModifier {
    let shape: Surface
    let interactive: Bool
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    @ViewBuilder
    func body(content: Content) -> some View {
        if reduceTransparency {
            content
                .background(Color(nsColor: .windowBackgroundColor), in: shape)
                .overlay(shape.strokeBorder(Color.primary.opacity(0.3), lineWidth: 1).allowsHitTesting(false))
        } else {
            surface(content)
                .overlay {
                    if contrast == .increased {
                        shape.strokeBorder(Color.primary.opacity(0.45), lineWidth: 1)
                            .allowsHitTesting(false)
                    }
                }
        }
    }

    @ViewBuilder
    private func surface(_ content: Content) -> some View {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            content.glassEffect(.regular.interactive(interactive), in: shape)
        } else {
            legacySurface(content)
        }
        #else
        legacySurface(content)
        #endif
    }

    private func legacySurface(_ content: Content) -> some View {
        content
            .background {
                DesktopMaterial()
                    .clipShape(shape)
                    .overlay {
                        shape.fill(LinearGradient(
                            colors: [.white.opacity(0.14), .clear, .white.opacity(0.03)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ))
                    }
            }
            .overlay(shape.strokeBorder(.white.opacity(0.24), lineWidth: 0.75).allowsHitTesting(false))
            .shadow(color: .black.opacity(0.16), radius: 16, x: 0, y: 6)
    }
}

private struct DesktopMaterial: NSViewRepresentable {
    // The material samples the desktop behind our transparent NSPanel.
    final class MaterialView: NSVisualEffectView {
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
    }

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = MaterialView()
        view.material = .hudWindow
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

extension View {
    func maxiGlass<S: InsettableShape>(in shape: S, interactive: Bool = false) -> some View {
        modifier(GlassSurface(shape: shape, interactive: interactive))
    }
}

struct HUDGlassGroup<Content: View>: View {
    @ViewBuilder var content: () -> Content

    @ViewBuilder var body: some View {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            GlassEffectContainer(spacing: 8, content: content)
        } else {
            content()
        }
        #else
        content()
        #endif
    }
}

// Use the property wrapper explicitly; newer SDKs also export a State macro.
private typealias HUDInteractionState<Value> = SwiftUI.State<Value>

// Bare controls keep generous hit targets without enclosing the icons.
struct HUDButtonStyle: ButtonStyle {
    var isSelected = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        ButtonBody(configuration: configuration, isSelected: isSelected, reduceMotion: reduceMotion)
    }

    private struct ButtonBody: View {
        let configuration: ButtonStyle.Configuration
        let isSelected: Bool
        let reduceMotion: Bool
        @HUDInteractionState private var hovered = false

        var body: some View {
            configuration.label
                .foregroundStyle(isSelected ? Color.accentColor : Color.primary.opacity(hovered ? 1 : 0.75))
                .opacity(configuration.isPressed ? 0.55 : 1)
                .contentShape(Capsule())
                .scaleEffect(configuration.isPressed && !reduceMotion ? 0.95 : 1)
                .animation(reduceMotion ? nil : .easeOut(duration: 0.16), value: hovered)
                .onHover { hovered = $0 }
        }
    }
}
