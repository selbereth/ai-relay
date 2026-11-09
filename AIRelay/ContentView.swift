import SwiftUI
import WatchKit

struct ContentView: View {
    @State private var token = Keychain.get("token")
    /// Bumped to rebuild the screens, so PairView starts a fresh pairing against the current server.
    @State private var epoch = 0

    var body: some View {
        NavigationStack {
            Group {
                if Config.serverURL == nil {
                    // First run, or the address was erased: ask for it before anything else.
                    SettingsView(isSetup: true, onRepair: {}, onServerChanged: { unpair() })
                } else if let token {
                    AskView(token: token, onUnpaired: { unpair() })
                } else {
                    PairView(onChange: { unpair() }) { newToken in
                        Keychain.set("token", newToken)
                        token = newToken
                    }
                }
            }
            .id(epoch)
        }
    }

    private func unpair() {
        Keychain.set("token", nil)
        token = nil
        epoch += 1
    }
}

/// Shows a short code; you type it on the server's web page and the watch picks up its token.
struct PairView: View {
    /// The server address or pairing was changed in Settings.
    let onChange: () -> Void
    let onPaired: (String) -> Void
    @State private var code: String?
    @State private var error: String?

    var body: some View {
        VStack(spacing: 6) {
            if let code {
                Text("Enter this code at").font(.footnote)
                Text(Config.serverURL?.host ?? "").font(.caption2).foregroundStyle(.secondary)
                Text(code).font(.system(.title, design: .monospaced).bold())
                ProgressView()
            } else if let error {
                Text(error).font(.footnote)
                Button("Retry") { Task { await run() } }
            } else {
                ProgressView()
            }
        }
        .task { await run() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) { SettingsGear(onChange: onChange) }
        }
    }

    private func run() async {
        error = nil
        do {
            let p = try await API.startPairing()
            code = p.code
            while true {
                try await Task.sleep(for: .seconds(2))
                if let token = try await API.poll(deviceSecret: p.device_secret) { onPaired(token); return }
            }
        } catch is CancellationError {
        } catch {
            code = nil
            self.error = "Pairing failed: \(error.localizedDescription)"
        }
    }
}

struct AskView: View {
    let token: String
    let onUnpaired: () -> Void
    @State private var question = ""
    @State private var answer: String?
    @State private var busy = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 6) {
                    questionBox
                    if !question.isEmpty {
                        // Removes the question and its answer, back to an empty screen.
                        Button { question = ""; answer = nil } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain)
                            .foregroundStyle(.secondary)
                            .accessibilityLabel("Clear")
                    }
                }
                if busy { ProgressView() }
                if let answer { Text(answer).font(.body) }
            }
        }
        .toolbar {
            // The gear is only there while the question box is empty.
            if question.isEmpty {
                ToolbarItem(placement: .topBarTrailing) { SettingsGear(onChange: onUnpaired) }
            }
        }
    }

    /// A watchOS text field only ever shows one truncated line. So once there is text, the question is shown as
    /// wrapped text (as many lines as it needs) with the real, invisible text field on top, so a tap still edits it.
    /// The page scrolls with the Digital Crown.
    @ViewBuilder private var questionBox: some View {
        if question.isEmpty {
            TextField("Ask AI", text: $question)
                .onSubmit { Task { await ask() } }
        } else {
            Text(question)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10)
                .padding(.vertical, 12)
                .background(Color.gray.opacity(0.25), in: RoundedRectangle(cornerRadius: 12))
                .overlay {
                    TextField("", text: $question)
                        .foregroundStyle(.clear)
                        .opacity(0.011)
                        .onSubmit { Task { await ask() } }
                }
        }
    }

    private func ask() async {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return }
        busy = true
        answer = nil
        defer { busy = false }
        do {
            answer = try await API.ask(q, token: token)
            WKInterfaceDevice.current().play(.success)
        } catch let e as APIError where e.message == "unpaired" {
            onUnpaired()
        } catch {
            answer = "Error: \(error.localizedDescription)"
        }
    }
}
