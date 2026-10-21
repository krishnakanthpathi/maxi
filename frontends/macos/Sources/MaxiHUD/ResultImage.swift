import Foundation

enum ResultImage {
    static func path(in output: String) -> String? {
        let pattern = #"!\[[^\]]*\]\(\s*(<[^>]+>|[^)]+?)\s*\)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let text = output as NSString
        let matches = regex.matches(in: output, range: NSRange(location: 0, length: text.length))
        for match in matches {
            var target = text.substring(with: match.range(at: 1))
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if target.hasPrefix("<") && target.hasSuffix(">") {
                target = String(target.dropFirst().dropLast())
            }
            let path: String
            if target.lowercased().hasPrefix("file://") {
                guard let url = URL(string: target), url.isFileURL,
                      url.host == nil || url.host == "" || url.host == "localhost" else { continue }
                path = url.path
            } else {
                guard target.hasPrefix("/") else { continue }
                path = target
            }
            let ext = (path as NSString).pathExtension.lowercased()
            var isDirectory: ObjCBool = false
            if ["png", "jpg", "jpeg", "gif"].contains(ext),
               FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory),
               !isDirectory.boolValue {
                return path
            }
        }
        return nil
    }
}
