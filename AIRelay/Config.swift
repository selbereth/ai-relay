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
        // The token travels with every request, so plain http is only accepted for addresses on your own network.
        if scheme == "http" && !isLocalHost(host) { return nil }
        return s
    }

    /// localhost, .local names and private IPv4 ranges (10.x, 172.16-31.x, 192.168.x, 127.x).
    private static func isLocalHost(_ host: String) -> Bool {
        let h = host.lowercased()
        if h == "localhost" || h.hasSuffix(".local") { return true }
        let parts = h.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4, h.split(separator: ".").count == 4 else { return false }
        return parts[0] == 10 || parts[0] == 127 || (parts[0] == 192 && parts[1] == 168) || (parts[0] == 172 && (16...31).contains(parts[1]))
    }

    static func store(_ address: String) { UserDefaults.standard.set(address, forKey: key) }
    static func clear() { UserDefaults.standard.removeObject(forKey: key) }
}
