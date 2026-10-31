import SwiftUI
import WatchKit

struct ContentView: View {
    @State private var token = Keychain.get("token")

    var body: some View {
        if let token {
            AskView(token: token) {
                Keychain.set("token", nil)
                self.token = nil
            }
        } else {
            PairView { newToken in
                Keychain.set("token", newToken)
                token = newToken
            }
        }
    }
}

/// Shows a short code; you type it on the server's web page and the watch picks up its token.
struct PairView: View {
    let onPaired: (String) -> Void
    @State private var code: String?
    @State private var error: String?

    var body: some View {
        VStack(spacing: 6) {
            if let code {
                Text("Enter this code at").font(.footnote)
                Text(Config.serverURL.host ?? "").font(.caption2).foregroundStyle(.secondary)
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
                TextField("Ask AI", text: $question)
                    .onSubmit { Task { await ask() } }
                if busy { ProgressView() }
                if let answer { Text(answer).font(.body) }
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
