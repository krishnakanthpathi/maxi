import AppKit

// Render the existing, bare summation mark as native macOS icon sizes.
let destination = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let image = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels,
            pixelsHigh: pixels, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
            isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        let context = NSGraphicsContext(bitmapImageRep: image)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        context.shouldAntialias = true
        let n = CGFloat(pixels)
        let path = NSBezierPath()
        path.move(to: NSPoint(x: n * 0.82, y: n * 0.86))
        path.line(to: NSPoint(x: n * 0.18, y: n * 0.86))
        path.line(to: NSPoint(x: n * 0.52, y: n * 0.50))
        path.line(to: NSPoint(x: n * 0.18, y: n * 0.14))
        path.line(to: NSPoint(x: n * 0.82, y: n * 0.14))
        path.lineWidth = n * 0.085
        path.lineCapStyle = .round
        path.lineJoinStyle = .round
        NSColor(srgbRed: 0.30, green: 0.39, blue: 0.19, alpha: 1).setStroke()
        path.stroke()
        NSGraphicsContext.restoreGraphicsState()
        let name = "icon_\(size)x\(size)" + (scale == 2 ? "@2x" : "") + ".png"
        try image.representation(using: .png, properties: [:])!.write(to: destination.appendingPathComponent(name))
    }
}
