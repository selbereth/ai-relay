import Foundation

enum Config {
    private static let overrideKey = "serverURL"

    /// The server running server/app.py (the Docker image).
    /// The built-in address lives in WatchClaude/LocalConfig.swift, which is not committed.
    /// Settings on the watch can override it; the override is kept in UserDefaults.
    static var serverURL: URL {
        if let s = UserDefaults.standard.string(forKey: overrideKey), let url = URL(string: s) { return url }
        return LocalConfig.serverURL
    }

    static var hasOverride: Bool { UserDefaults.standard.string(forKey: overrideKey) != nil }

    /// Saves a new server address. Returns false if it is not a usable http(s) address.
    @discardableResult
    static func setServerURL(_ text: String) -> Bool {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return false }
        if !s.contains("://") { s = "https://" + s }
        while s.hasSuffix("/") { s.removeLast() }
        guard let url = URL(string: s), let scheme = url.scheme?.lowercased(),
              scheme == "https" || scheme == "http", let host = url.host, !host.isEmpty else { return false }
        UserDefaults.standard.set(s, forKey: overrideKey)
        return true
    }

    static func resetServerURL() {
        UserDefaults.standard.removeObject(forKey: overrideKey)
    }
}
