import Foundation

/// The server address is set on the watch (Settings) and kept in UserDefaults. There is no built-in address.
enum Config {
    private static let key = "serverURL"

    /// The saved address as a full URL, or nil until one has been entered.
    static var serverURL: URL? {
        guard let s = stored else { return nil }
        return URL(string: s)
    }

    /// The saved address exactly as stored (always has a scheme).
    static var stored: String? { UserDefaults.standard.string(forKey: key) }

    /// The saved address without "https://", the way it is shown and typed.
    static var displayText: String {
        guard let s = stored else { return "" }
        return s.hasPrefix("https://") ? String(s.dropFirst("https://".count)) : s
    }

    /// Turns what the user typed into a full address: "claude.abc.com" becomes "https://claude.abc.com".
    /// An explicit http:// or https:// is kept. Returns nil if the text is not a usable address.
    static func normalize(_ text: String) -> String? {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        if !s.contains("://") { s = "https://" + s }
        while s.hasSuffix("/") { s.removeLast() }
        guard let url = URL(string: s), let scheme = url.scheme?.lowercased(),
              scheme == "https" || scheme == "http", let host = url.host, !host.isEmpty else { return nil }
        return s
    }

    static func store(_ address: String) { UserDefaults.standard.set(address, forKey: key) }
    static func clear() { UserDefaults.standard.removeObject(forKey: key) }
}
