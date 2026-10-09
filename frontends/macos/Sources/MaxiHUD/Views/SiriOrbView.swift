import SwiftUI

public final class OrbAnimationModel: ObservableObject {
    @Published public var rotatePhase: Double = 0
    @Published public var pulseScale: CGFloat = 1.0
    @Published public var rippleScale: CGFloat = 1.0
    @Published public var rippleOpacity: Double = 0.6

    public init() {}
}

public struct SiriOrbView: View {
    @ObservedObject var appState: AppState
    @StateObject private var anim = OrbAnimationModel()
    var size: CGFloat = 38

    public init(appState: AppState, size: CGFloat = 38) {
        self.appState = appState
        self.size = size
    }

    public var body: some View {
        ZStack {
            // Background ambient glow halo
            Circle()
                .fill(haloGradient)
                .frame(width: size * 1.5, height: size * 1.5)
                .blur(radius: size * 0.35)
                .opacity(ambientGlowOpacity)

            // Animated acoustic ripple ring (active while listening)
            if appState.voiceState == .listening {
                Circle()
                    .stroke(
                        LinearGradient(
                            colors: [Color.pink.opacity(0.8), Color.cyan.opacity(0.4)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 2
                    )
                    .frame(width: size * anim.rippleScale, height: size * anim.rippleScale)
                    .opacity(anim.rippleOpacity)
            }

            // Core multi-layered plasma orb
            ZStack {
                // Base glowing disc
                Circle()
                    .fill(baseGradient)

                // Swirling chromatic angular layer
                Circle()
                    .fill(
                        AngularGradient(
                            gradient: Gradient(colors: gradientColors),
                            center: .center,
                            angle: .degrees(anim.rotatePhase)
                        )
                    )
                    .blendMode(.screen)
                    .opacity(0.85)

                // Specular lens flare highlight
                Circle()
                    .fill(
                        RadialGradient(
                            gradient: Gradient(colors: [
                                Color.white.opacity(0.7),
                                Color.white.opacity(0.1),
                                Color.clear
                            ]),
                            center: .topLeading,
                            startRadius: 2,
                            endRadius: size * 0.7
                        )
                    )
                    .blendMode(.overlay)
            }
            .frame(width: size, height: size)
            .scaleEffect(anim.pulseScale)
            .shadow(color: shadowColor, radius: 8, x: 0, y: 0)
        }
        .onAppear {
            startAnimations()
        }
        .onChange(of: appState.voiceState) { _ in
            updateAnimationsForState()
        }
    }

    private var gradientColors: [Color] {
        switch appState.voiceState {
        case .listening:
            return [
                Color(red: 1.0, green: 0.2, blue: 0.5),   // Hot Pink
                Color(red: 0.6, green: 0.2, blue: 1.0),   // Violet
                Color(red: 0.0, green: 0.8, blue: 1.0),   // Electric Cyan
                Color(red: 1.0, green: 0.6, blue: 0.0),   // Neon Amber
                Color(red: 1.0, green: 0.2, blue: 0.5)
            ]
        case .processing:
            return [
                Color(red: 0.0, green: 0.85, blue: 1.0),  // Cyan
                Color(red: 0.3, green: 0.4, blue: 1.0),   // Cobalt
                Color(red: 0.7, green: 0.2, blue: 0.9),   // Purple
                Color(red: 0.0, green: 0.85, blue: 1.0)
            ]
        case .streaming:
            return [
                Color(red: 0.1, green: 0.8, blue: 0.6),   // Teal / Emerald
                Color(red: 0.0, green: 0.85, blue: 1.0),  // Cyan
                Color(red: 0.2, green: 0.5, blue: 1.0),   // Blue
                Color(red: 0.1, green: 0.8, blue: 0.6)
            ]
        case .completed:
            return [
                Color(red: 0.06, green: 0.75, blue: 0.55),
                Color(red: 0.0, green: 0.82, blue: 1.0),
                Color(red: 0.06, green: 0.75, blue: 0.55)
            ]
        case .idle:
            return [
                Color(red: 0.0, green: 0.75, blue: 0.95),
                Color(red: 0.25, green: 0.35, blue: 0.85),
                Color(red: 0.0, green: 0.75, blue: 0.95)
            ]
        }
    }

    private var baseGradient: RadialGradient {
        RadialGradient(
            gradient: Gradient(colors: [
                Color(red: 0.1, green: 0.2, blue: 0.4),
                Color(red: 0.05, green: 0.07, blue: 0.15)
            ]),
            center: .center,
            startRadius: 2,
            endRadius: size
        )
    }

    private var haloGradient: RadialGradient {
        RadialGradient(
            gradient: Gradient(colors: [
                appState.voiceState == .listening ? Color.pink : Color.cyan,
                Color.clear
            ]),
            center: .center,
            startRadius: 4,
            endRadius: size * 0.9
        )
    }

    private var ambientGlowOpacity: Double {
        switch appState.voiceState {
        case .listening: return 0.85
        case .processing: return 0.7
        case .streaming: return 0.6
        case .completed: return 0.4
        case .idle: return 0.3
        }
    }

    private var shadowColor: Color {
        switch appState.voiceState {
        case .listening: return Color.pink.opacity(0.6)
        case .processing: return Color.cyan.opacity(0.6)
        case .streaming: return Color.teal.opacity(0.5)
        case .completed: return Color.green.opacity(0.4)
        case .idle: return Color.cyan.opacity(0.25)
        }
    }

    private func startAnimations() {
        withAnimation(.linear(duration: 8.0).repeatForever(autoreverses: false)) {
            anim.rotatePhase = 360
        }
        updateAnimationsForState()
    }

    private func updateAnimationsForState() {
        switch appState.voiceState {
        case .listening:
            withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true)) {
                anim.pulseScale = 1.15
            }
            withAnimation(.easeOut(duration: 1.2).repeatForever(autoreverses: false)) {
                anim.rippleScale = 1.7
                anim.rippleOpacity = 0.0
            }

        case .processing:
            withAnimation(.linear(duration: 2.0).repeatForever(autoreverses: false)) {
                anim.rotatePhase += 360
            }
            withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) {
                anim.pulseScale = 1.08
            }
            anim.rippleScale = 1.0
            anim.rippleOpacity = 0.0

        case .streaming:
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                anim.pulseScale = 1.05
            }
            anim.rippleScale = 1.0
            anim.rippleOpacity = 0.0

        default:
            withAnimation(.easeInOut(duration: 2.0).repeatForever(autoreverses: true)) {
                anim.pulseScale = 1.0
            }
            anim.rippleScale = 1.0
            anim.rippleOpacity = 0.0
        }
    }
}
