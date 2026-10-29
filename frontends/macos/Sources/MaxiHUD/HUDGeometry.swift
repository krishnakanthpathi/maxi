import SwiftUI

enum HUDGeometry {
    static let cornerRadius: CGFloat = 24
    static let notchGap: CGFloat = 12
    static let cardGap: CGFloat = 14

    static func topEdge(fullFrame: CGRect, visibleFrame: CGRect, safeTop: CGFloat) -> CGFloat {
        min(visibleFrame.maxY, fullFrame.maxY - safeTop) - notchGap
    }

    static func hitSurface(_ point: CGPoint, size: CGSize, pillSize: CGSize, atTop: Bool, hasResponse: Bool) -> Bool {
        let pill = CGRect(x: (size.width - pillSize.width) / 2,
                          y: atTop ? 0 : size.height - pillSize.height,
                          width: pillSize.width, height: pillSize.height)
        if Capsule().path(in: pill).contains(point) { return true }
        guard hasResponse else { return false }
        let card = CGRect(x: 0, y: atTop ? pillSize.height + cardGap : 0,
                          width: size.width, height: max(0, size.height - pillSize.height - cardGap))
        return RoundedRectangle(cornerRadius: 26, style: .continuous).path(in: card).contains(point)
    }
}

struct HUDSizePreference: PreferenceKey {
    static let defaultValue = CGSize.zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
        let next = nextValue()
        if next.width > 0 && next.height > 0 { value = next }
    }
}

struct ToastHeightPreference: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

struct PillSizePreference: PreferenceKey {
    static let defaultValue = CGSize.zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
        let next = nextValue()
        if next.width > 0 && next.height > 0 { value = next }
    }
}
