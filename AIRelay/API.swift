import Foundation

struct APIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

enum API {
    struct Pairing: Decodable {
        let code: String
        let device_secret: String
    }

    private struct PollResult: Decodable { let status: String; let token: String? }
    private struct AskResult: Decodable { let answer: String?; let error: String? }

    struct Model: Decodable, Hashable, Identifiable {
        let id: String
        let name: String
    }
    struct ModelList: Decodable {
        let `default`: String
        let models: [Model]
    }

    private static func send<T: Decodable>(_ path: String, body: [String: String] = [:], token: String? = nil,
                                           timeout: TimeInterval = 30, method: String = "POST") async throws -> (T, Int) {
        guard let base = Config.serverURL else { throw APIError(message: "No server address") }
        var req = URLRequest(url: base.appendingPathComponent(path), timeoutInterval: timeout)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if method == "POST" { req.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, resp) = try await URLSession.shared.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        return (try JSONDecoder().decode(T.self, from: data), status)
    }

    static func startPairing() async throws -> Pairing {
        try await send("pair/start").0
    }

    /// Returns the token once the web login has approved the code, nil while still pending.
    static func poll(deviceSecret: String) async throws -> String? {
        let (r, _): (PollResult, Int) = try await send("pair/poll", body: ["device_secret": deviceSecret])
        return r.status == "approved" ? r.token : nil
    }

    /// The models the server offers. The chosen one is kept in UserDefaults ("model"); empty means the server default.
    static func models(token: String) async throws -> ModelList {
        try await send("models", token: token, method: "GET").0
    }

    static var chosenModel: String { UserDefaults.standard.string(forKey: "model") ?? "" }

    static func ask(_ question: String, token: String) async throws -> String {
        var body = ["question": question]
        if !chosenModel.isEmpty { body["model"] = chosenModel }
        let (r, status): (AskResult, Int) = try await send("ask", body: body, token: token, timeout: 100)
        if status == 401 { throw APIError(message: "unpaired") }
        if let answer = r.answer { return answer }
        throw APIError(message: r.error ?? "No answer")
    }
}
