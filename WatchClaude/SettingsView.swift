import SwiftUI

/// Reached from the gear button on every screen: change the server address, or pair the watch again.
struct SettingsView: View {
    /// Forget the token and start pairing again (same server).
    let onRepair: () -> Void
    /// The server address changed: the old token belongs to the old server, so pair again.
    let onServerChanged: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var urlText = Config.serverURL.absoluteString
    @State private var custom = Config.hasOverride
    @State private var message: String?
    @State private var confirmRepair = false

    var body: some View {
        List {
            Section("Server address") {
                TextField("https://…", text: $urlText)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Save address") {
                    let before = Config.serverURL
                    if Config.setServerURL(urlText) {
                        urlText = Config.serverURL.absoluteString
                        custom = true
                        message = "Saved"
                        if Config.serverURL != before { onServerChanged(); dismiss() }
                    } else {
                        message = "Not a valid address"
                    }
                }
                if custom {
                    Button("Use built-in address") {
                        let before = Config.serverURL
                        Config.resetServerURL()
                        urlText = Config.serverURL.absoluteString
                        custom = false
                        message = "Using built-in address"
                        if Config.serverURL != before { onServerChanged(); dismiss() }
                    }
                }
                if let message { Text(message).font(.footnote).foregroundStyle(.secondary) }
            }
            Section("Pairing") {
                Button("Re-pair this watch", role: .destructive) { confirmRepair = true }
            }
        }
        .navigationTitle("Settings")
        .confirmationDialog("Forget this pairing and get a new code?", isPresented: $confirmRepair, titleVisibility: .visible) {
            Button("Re-pair", role: .destructive) { onRepair(); dismiss() }
            Button("Cancel", role: .cancel) {}
        }
    }
}
