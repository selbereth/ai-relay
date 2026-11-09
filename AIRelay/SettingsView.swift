import SwiftUI

/// The server address and pairing. It is the first screen when no address has been entered yet (`isSetup`),
/// and is otherwise reached from the gear button. The address saves by itself: on return, and when you leave the screen.
struct SettingsView: View {
    let isSetup: Bool
    /// Forget the token and start pairing again (same server).
    let onRepair: () -> Void
    /// The server address changed: the old token belongs to the old server, so pair again.
    let onServerChanged: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text = Config.displayText
    @State private var confirmRepair = false

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var invalid: Bool { !trimmed.isEmpty && Config.normalize(trimmed) == nil }

    var body: some View {
        List {
            Section(isSetup ? "Enter your server address" : "Server address") {
                TextField("claude.example.com", text: $text)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onSubmit { commit() }
                if invalid {
                    Text("Not a valid address").font(.footnote).foregroundStyle(.red)
                }
            }
            if !isSetup {
                Section("Pairing") {
                    Button("Re-pair this watch", role: .destructive) { confirmRepair = true }
                }
            }
        }
        .navigationTitle(isSetup ? "AI Relay" : "Settings")
        .onDisappear { if !isSetup { commit() } }
        .confirmationDialog("Forget this pairing and get a new code?", isPresented: $confirmRepair, titleVisibility: .visible) {
            Button("Re-pair", role: .destructive) { onRepair(); dismiss() }
            Button("Cancel", role: .cancel) {}
        }
    }

    /// Saves what is in the field. An empty field removes the address; an invalid one is ignored (the old address stays).
    private func commit() {
        if trimmed.isEmpty {
            if Config.stored != nil { Config.clear(); onServerChanged() }
            return
        }
        guard let address = Config.normalize(trimmed), address != Config.stored else { return }
        Config.store(address)
        onServerChanged()
    }
}

/// The gear that opens Settings. `onChange` runs when the address changes or the watch is re-paired.
struct SettingsGear: View {
    let onChange: () -> Void

    var body: some View {
        NavigationLink {
            SettingsView(isSetup: false, onRepair: onChange, onServerChanged: onChange)
        } label: {
            Image(systemName: "gearshape")
        }
    }
}
