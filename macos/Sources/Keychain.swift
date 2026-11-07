import Foundation
import Security

/// The Jellyfin API key in this Mac's login Keychain: a generic password with service
/// "flalac-jellyfin" and the Jellyfin user as account. It is never written anywhere else.
enum Keychain {
    static let service = "flalac-jellyfin"
    static let label = "flalac Jellyfin API key"

    struct Failure: Error, Equatable {
        var status: OSStatus

        var message: String {
            let text = SecCopyErrorMessageString(status, nil) as String? ?? "Error \(status)"
            return "Keychain: \(text)"
        }
    }

    /// The key saved for `account`, or nil when there is none.
    static func key(for account: String) throws -> String? {
        var query = baseQuery(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        switch status {
        case errSecSuccess:
            guard let data = item as? Data else { return nil }
            return String(decoding: data, as: UTF8.self)
        case errSecItemNotFound:
            return nil
        default:
            throw Failure(status: status)
        }
    }

    /// Saves the key for `account`, replacing the one saved before.
    static func setKey(_ key: String, for account: String) throws {
        let data = Data(key.utf8)
        let update = SecItemUpdate(baseQuery(account) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        switch update {
        case errSecSuccess:
            return
        case errSecItemNotFound:
            var item = baseQuery(account)
            item[kSecAttrLabel as String] = label
            item[kSecValueData as String] = data
            let status = SecItemAdd(item as CFDictionary, nil)
            if status != errSecSuccess {
                throw Failure(status: status)
            }
        default:
            throw Failure(status: update)
        }
    }

    static func deleteKey(for account: String) throws {
        let status = SecItemDelete(baseQuery(account) as CFDictionary)
        if status != errSecSuccess, status != errSecItemNotFound {
            throw Failure(status: status)
        }
    }

    private static func baseQuery(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}
