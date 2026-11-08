import Foundation

enum Config {
    /// The server running server/app.py (the Docker image).
    /// The address lives in WatchClaude/LocalConfig.swift, which is not committed.
    static let serverURL = LocalConfig.serverURL
}
