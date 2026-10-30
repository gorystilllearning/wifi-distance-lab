import AppKit
import CoreLocation
import CoreWLAN
import Foundation

// An actual app bundle is needed for a useful Location Services permission flow.
// Nothing scans for networks or changes the current Wi-Fi connection.
final class AppDelegate: NSObject, NSApplicationDelegate, CLLocationManagerDelegate {
    private let location = CLLocationManager()
    private let wlan = CWWiFiClient.shared()
    private var timer: Timer?
    private var window: NSWindow?
    private var statusLabel: NSTextField?
    private let output: URL
    private let interfaceName: String?

    override init() {
        let args = CommandLine.arguments
        func argument(_ flag: String) -> String? {
            guard let i = args.firstIndex(of: flag), i + 1 < args.count else { return nil }
            return args[i + 1]
        }
        let path = argument("--output") ?? NSHomeDirectory() + "/Library/Caches/WifiDistanceLab/rssi.json"
        output = URL(fileURLWithPath: path)
        interfaceName = argument("--interface")
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 150),
                         styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        w.title = "Wi-Fi Distance Lab — RSSI"
        let label = NSTextField(wrappingLabelWithString: "Allow Location Services to read native Wi-Fi RSSI.\nConnect to the Windows hotspot.")
        label.frame = NSRect(x: 18, y: 18, width: 504, height: 110)
        w.contentView?.addSubview(label)
        w.center()
        w.makeKeyAndOrderFront(nil)
        window = w
        statusLabel = label
        NSApp.activate(ignoringOtherApps: true)
        location.delegate = self
        location.requestWhenInUseAuthorization()
        sample()
        timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in self?.sample() }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        sample()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func sample() {
        var row: [String: Any] = ["timestamp": Date().timeIntervalSince1970,
                                  "rssi_dbm": NSNull(), "ssid": "", "bssid": "", "source": "CoreWLAN"]
        var reason = ""
        let permission = location.authorizationStatus
        // macOS uses authorizedAlways; authorizedWhenInUse is iOS-only.
        let allowed = permission == .authorizedAlways
        if !CLLocationManager.locationServicesEnabled() {
            reason = "Location Services disabled"
        } else if !allowed {
            reason = "Location permission not granted (status \(permission.rawValue))"
        } else if let iface = interfaceName.flatMap({ wlan.interface(withName: $0) }) ?? wlan.interface() {
            row["interface"] = iface.interfaceName ?? ""
            row["ssid"] = iface.ssid() ?? ""
            row["bssid"] = iface.bssid() ?? ""
            let value = iface.rssiValue()
            if !iface.powerOn() {
                reason = "Wi-Fi interface powered off"
            } else if iface.ssid() == nil || iface.bssid() == nil {
                reason = "SSID/BSSID unavailable: disconnected or macOS privacy restriction"
            } else if value >= -127 && value < 0 {
                row["rssi_dbm"] = value
            } else {
                reason = "CoreWLAN did not return valid native RSSI (\(value))"
            }
        } else {
            reason = "No Wi-Fi interface found"
        }
        row["reason"] = reason
        do {
            try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            try data.write(to: output, options: .atomic)
            let value = row["rssi_dbm"] is NSNull ? "unavailable" : "\(row["rssi_dbm"]!) dBm"
            statusLabel?.stringValue = "SSID: \(row["ssid"] ?? "")\nBSSID: \(row["bssid"] ?? "")\nRSSI: \(value)\n\(reason.isEmpty ? "Native CoreWLAN reading; leave this window open." : reason)"
        } catch {
            statusLabel?.stringValue = "Cannot save RSSI: \(error.localizedDescription)"
        }
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
