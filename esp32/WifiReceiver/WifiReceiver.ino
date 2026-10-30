/* Windows hotspot -> ESP32-S3 receiver. Arduino-ESP32 3.3.12.
 * Payload is never held in RAM: only a 4096-byte streaming buffer.
 * cJSON, LittleFS, Preferences, WiFi ship with the ESP32 core.
 */
#include <WiFi.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <esp_timer.h>
#include <cJSON.h>
#include <math.h>
#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif

static const uint32_t TARGET = 10000000;
static const size_t MAX_CONTROL = 4096;
static const size_t MAX_REPORT = 131072;
static uint8_t payloadBuffer[4096];
static WiFiClient linkClient;
static Preferences prefs;
static String token, receiverId, lineBuffer, serialLine;
static bool fsReady = false;
static uint32_t retryAt = 0;

static int64_t microsNow() { return esp_timer_get_time(); }

static const char* text(const cJSON* obj, const char* name) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(obj, name);
  return cJSON_IsString(v) && v->valuestring ? v->valuestring : "";
}

static double number(const cJSON* obj, const char* name, double fallback = -1) {
  const cJSON* v = cJSON_GetObjectItemCaseSensitive(obj, name);
  return cJSON_IsNumber(v) ? v->valuedouble : fallback;
}

static bool isType(const cJSON* obj, const char* kind) {
  return obj && strcmp(text(obj, "type"), kind) == 0;
}

static cJSON* frame(const char* kind, const char* id = nullptr) {
  cJSON* obj = cJSON_CreateObject();
  cJSON_AddStringToObject(obj, "type", kind);
  if (id) cJSON_AddStringToObject(obj, "test_id", id);
  return obj;
}

static bool sendRaw(const String& data, uint32_t timeoutMs = 15000) {
  size_t offset = 0;
  int64_t deadline = microsNow() + (int64_t)timeoutMs * 1000;
  while (offset < data.length()) {
    if (!linkClient.connected() || microsNow() >= deadline) return false;
    size_t n = linkClient.write((const uint8_t*)data.c_str() + offset,
                                min((size_t)1024, data.length() - offset));
    offset += n;
    delay(1);
  }
  return true;
}

static bool sendFrame(cJSON* obj) {
  char* raw = cJSON_PrintUnformatted(obj);
  if (!raw) return false;
  String data(raw);
  cJSON_free(raw);
  data += '\n';
  return sendRaw(data);
}

// The buffer survives an idle timeout, so fragmented JSON isn't discarded.
static cJSON* readFrame(uint32_t timeoutMs) {
  int64_t deadline = microsNow() + (int64_t)timeoutMs * 1000;
  while (microsNow() < deadline) {
    while (linkClient.available()) {
      int c = linkClient.read();
      if (c < 0) break;
      if (c == '\n') {
        cJSON* obj = cJSON_Parse(lineBuffer.c_str());
        lineBuffer = "";
        if (!cJSON_IsObject(obj)) {
          cJSON_Delete(obj);
          linkClient.stop();
          return nullptr;
        }
        return obj;
      }
      lineBuffer += (char)c;
      if (lineBuffer.length() > MAX_CONTROL) {
        linkClient.stop();
        lineBuffer = "";
        return nullptr;
      }
    }
    if (!linkClient.connected()) return nullptr;
    delay(1);
  }
  return nullptr;
}

static bool ackFor(const char* id) {
  cJSON* ack = readFrame(15000);
  bool good = isType(ack, "ack") && strcmp(text(ack, "test_id"), id) == 0;
  cJSON_Delete(ack);
  return good;
}

static bool saveReport(const String& report) {
  if (!fsReady || LittleFS.exists("/pending.json")) return false;
  File f = LittleFS.open("/pending.tmp", "w");
  if (!f) return false;
  size_t written = f.print(report);
  f.flush();
  f.close();
  if (written != report.length()) return false;
  return LittleFS.rename("/pending.tmp", "/pending.json");
}

static bool replayPending() {
  if (!LittleFS.exists("/pending.json")) return true;
  File f = LittleFS.open("/pending.json", "r");
  if (!f || f.size() > MAX_REPORT) return false;
  String raw = f.readString();
  f.close();
  cJSON* obj = cJSON_Parse(raw.c_str());
  if (!isType(obj, "result")) {
    cJSON_Delete(obj);
    Serial.println("ERROR: pending report corrupt. Do not format; preserve it for recovery.");
    return false;
  }
  String id = text(obj, "test_id");
  cJSON_Delete(obj);
  if (!sendRaw(raw + "\n") || !ackFor(id.c_str())) return false;
  return LittleFS.remove("/pending.json");
}

static bool handshake() {
  cJSON* hello = frame("hello");
  cJSON_AddNumberToObject(hello, "protocol", 1);
  cJSON_AddStringToObject(hello, "token", token.c_str());
  cJSON_AddStringToObject(hello, "device", "esp32");
  cJSON_AddStringToObject(hello, "receiver_id", receiverId.c_str());
  cJSON_AddStringToObject(hello, "ssid", WiFi.SSID().c_str());
  cJSON_AddNumberToObject(hello, "pending_count", LittleFS.exists("/pending.json") ? 1 : 0);
  bool sent = sendFrame(hello);
  cJSON_Delete(hello);
  if (!sent) return false;
  cJSON* reply = readFrame(10000);
  bool good = isType(reply, "welcome");
  cJSON_Delete(reply);
  return good && replayPending();
}

static void addRssi(cJSON* samples, int64_t start, bool& missing) {
  cJSON* s = cJSON_CreateObject();
  cJSON_AddNumberToObject(s, "elapsed_ms", (microsNow() - start) / 1000.0);
  // Identity is in the report envelope, not duplicated 240 times in SRAM.
  int rssi = WiFi.RSSI();
  if (WiFi.status() == WL_CONNECTED && rssi >= -127 && rssi < 0 && WiFi.SSID() == WIFI_SSID) {
    cJSON_AddNumberToObject(s, "rssi_dbm", rssi);
  } else {
    missing = true;
    cJSON_AddNullToObject(s, "rssi_dbm");
    cJSON_AddStringToObject(s, "reason", "Station disconnected or native RSSI unavailable");
  }
  cJSON_AddItemToArray(samples, s);
}

static cJSON* receivePayload(double timeoutSeconds, const String& bssid) {
  cJSON* result = cJSON_CreateObject();
  cJSON* samples = cJSON_AddArrayToObject(result, "rssi_samples");
  uint32_t received = 0;
  const char* status = "success";
  const char* reason = "";
  bool missing = false;
  int64_t start = microsNow();
  int64_t deadline = start + (int64_t)(timeoutSeconds * 1000000.0);
  int64_t interval = max((int64_t)250000, (int64_t)(timeoutSeconds * 1000000.0 / 240));
  int64_t nextSample = start;
  while (received < TARGET) {
    int64_t now = microsNow();
    if (now >= nextSample) {
      addRssi(samples, start, missing);
      nextSample = now + interval;
    }
    if (now >= deadline) {
      status = "timeout";
      reason = "Total payload deadline exceeded";
      break;
    }
    int available = linkClient.available();
    if (available > 0) {
      size_t wanted = min(sizeof(payloadBuffer), (size_t)(TARGET - received));
      wanted = min(wanted, (size_t)available);
      int n = linkClient.read(payloadBuffer, wanted);
      if (n > 0) received += n;
      else if (n < 0) {
        status = "connection_disconnected";
        reason = "TCP read failed";
        break;
      }
    } else if (WiFi.status() != WL_CONNECTED) {
      status = "connection_disconnected";
      reason = "Wi-Fi association lost";
      break;
    } else if (!linkClient.connected()) {
      status = "transfer_incomplete";
      reason = "TCP closed before target; Arduino API cannot distinguish FIN from reset here";
      break;
    } else {
      delay(1);
    }
  }
  double duration = (microsNow() - start) / 1000000.0;
  cJSON_AddNumberToObject(result, "bytes_received", received);
  cJSON_AddNumberToObject(result, "duration_s", duration > 0 ? duration : 0.000001);
  cJSON_AddStringToObject(result, "status", status);
  cJSON_AddStringToObject(result, "failure_reason", reason);
  cJSON_AddBoolToObject(result, "transfer_complete", received == TARGET);
  cJSON_AddStringToObject(result, "rssi_reason", missing ? "Some native RSSI samples unavailable; inspect raw samples" : "");
  cJSON_AddStringToObject(result, "timer", "esp_timer_get_time (microseconds, monotonic)");
  return result;
}

static bool validId(const String& id) {
  if (!id.length() || id.length() > 100) return false;
  for (size_t i = 0; i < id.length(); ++i) {
    char c = id[i];
    if (!isalnum((unsigned char)c) && c != '-' && c != '_') return false;
  }
  return true;
}

static bool runTrial(cJSON* request) {
  String id = text(request, "test_id");
  double timeoutSeconds = number(request, "timeout_s");
  if (!validId(id) || number(request, "target_bytes") != TARGET || !isfinite(timeoutSeconds) ||
      timeoutSeconds <= 0 || timeoutSeconds > 600 || LittleFS.exists("/pending.json")) return false;
  if (LittleFS.totalBytes() - LittleFS.usedBytes() < MAX_REPORT * 2) return false;
  String bssid = WiFi.BSSIDstr();
  Serial.printf("Trial %s; RSSI %d dBm\n", id.c_str(), WiFi.RSSI());
  cJSON* ready = frame("ready", id.c_str());
  bool good = sendFrame(ready);
  cJSON_Delete(ready);
  cJSON* result = nullptr;
  while (good) {
    cJSON* command = readFrame(650000);
    if (!command || strcmp(text(command, "test_id"), id.c_str()) != 0) {
      cJSON_Delete(command);
      break;
    }
    if (isType(command, "echo")) {
      cJSON* pong = frame("pong", id.c_str());
      cJSON_AddNumberToObject(pong, "seq", number(command, "seq"));
      good = sendFrame(pong);
      cJSON_Delete(pong);
    } else if (isType(command, "transfer") && number(command, "target_bytes") == TARGET &&
               number(command, "timeout_s") == timeoutSeconds) {
      cJSON* payloadReady = frame("payload_ready", id.c_str());
      good = sendFrame(payloadReady);
      cJSON_Delete(payloadReady);
      if (good) result = receivePayload(timeoutSeconds, bssid);
      cJSON_Delete(command);
      break;
    } else {
      good = false;
    }
    cJSON_Delete(command);
  }
  if (!result) {
    result = cJSON_CreateObject();
    cJSON_AddNumberToObject(result, "bytes_received", 0);
    cJSON_AddNullToObject(result, "duration_s");
    cJSON_AddBoolToObject(result, "transfer_complete", false);
    cJSON_AddBoolToObject(result, "before_payload", true);
    cJSON_AddStringToObject(result, "status", "connection_disconnected");
    cJSON_AddStringToObject(result, "failure_reason", "Disconnected or invalid control frame before payload");
    cJSON_AddStringToObject(result, "rssi_reason", "Payload did not start");
    cJSON_AddArrayToObject(result, "rssi_samples");
  }
  bool success = strcmp(text(result, "status"), "success") == 0;
  cJSON* report = frame("result", id.c_str());
  cJSON_AddStringToObject(report, "device", "esp32");
  cJSON_AddStringToObject(report, "receiver_id", receiverId.c_str());
  cJSON_AddStringToObject(report, "ssid", WIFI_SSID);
  cJSON_AddStringToObject(report, "bssid", bssid.c_str());
  cJSON_AddItemToObject(report, "result", result);
  char* raw = cJSON_PrintUnformatted(report);
  if (!raw) {
    cJSON_Delete(report);
    return false;
  }
  String encoded(raw);
  cJSON_free(raw);
  cJSON_Delete(report);
  if (!saveReport(encoded)) {
    Serial.println("FATAL: cannot persist report. No new trial allowed; inspect flash.");
    linkClient.stop();
    // Keep a RAM copy as well; never silently discard an uncommitted result.
    while (!saveReport(encoded)) delay(1000);
    return false;
  }
  Serial.printf("Saved result for %s; %s\n", id.c_str(), success ? "complete" : "failed/partial");
  return replayPending() && success;
}

static void serialCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      serialLine.trim();
      if (serialLine.startsWith("TOKEN ")) {
        String updated = serialLine.substring(6);
        updated.trim();
        bool valid = updated.length() == 32;
        for (size_t i = 0; i < updated.length(); ++i) valid = valid && isxdigit((unsigned char)updated[i]);
        if (valid) {
          token = updated;
          prefs.putString("token", token);
          linkClient.stop();
          Serial.println("Session token saved. Reconnecting. Pending reports are NOT deleted.");
        } else Serial.println("TOKEN must contain 32 hexadecimal characters.");
      } else if (serialLine == "STATUS") {
        Serial.printf("Wi-Fi %d, IP %s, SSID %s, BSSID %s, RSSI %d, pending %d\n",
                      WiFi.status(), WiFi.localIP().toString().c_str(), WiFi.SSID().c_str(),
                      WiFi.BSSIDstr().c_str(), WiFi.RSSI(), LittleFS.exists("/pending.json"));
      }
      serialLine = "";
    } else if (serialLine.length() < 128) serialLine += c;
  }
}

void setup() {
  Serial.begin(115200);
  prefs.begin("wifi-lab", false);
  token = prefs.getString("token", SESSION_TOKEN);
  char id[32];
  snprintf(id, sizeof(id), "esp-%012llx", (unsigned long long)ESP.getEfuseMac());
  receiverId = id;
  fsReady = LittleFS.begin(false);
  if (!fsReady) {
    Serial.println("LittleFS not mounted. First installation only: send FORMAT + newline to erase this sketch filesystem.");
    Serial.println("Do NOT format if it may contain an unreported result.");
    String confirmation;
    while (!fsReady) {
      if (Serial.available()) {
        char c = Serial.read();
        if (c == '\n') {
          confirmation.trim();
          if (confirmation == "FORMAT") fsReady = LittleFS.format() && LittleFS.begin(false);
          confirmation = "";
        } else if (confirmation.length() < 16) confirmation += c;
      }
      delay(10);
    }
  }
  // Recover a completed temp-file rename after a power loss, if valid.
  if (!LittleFS.exists("/pending.json") && LittleFS.exists("/pending.tmp")) {
    File f = LittleFS.open("/pending.tmp", "r");
    String raw = f.readString();
    f.close();
    cJSON* obj = cJSON_Parse(raw.c_str());
    if (isType(obj, "result")) LittleFS.rename("/pending.tmp", "/pending.json");
    else Serial.println("Incomplete temporary report found; retain filesystem for inspection.");
    cJSON_Delete(obj);
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Receiver %s. Serial commands: TOKEN <token>, STATUS\n", receiverId.c_str());
}

void loop() {
  serialCommands();
  if (WiFi.status() != WL_CONNECTED) {
    delay(50);
    return;
  }
  if (!linkClient.connected()) {
    if ((int32_t)(millis() - retryAt) < 0) {
      delay(10);
      return;
    }
    linkClient.stop();
    lineBuffer = "";
    retryAt = millis() + 3000;
    if (!linkClient.connect(WINDOWS_HOST, WINDOWS_PORT, 3000)) return;
    linkClient.setNoDelay(true);
    linkClient.setTimeout(2);
    if (!handshake()) {
      Serial.println("Handshake/recovery failed; check token and Windows --resume session.");
      linkClient.stop();
      return;
    }
    Serial.printf("Connected to Windows, SSID %s BSSID %s RSSI %d\n", WiFi.SSID().c_str(), WiFi.BSSIDstr().c_str(), WiFi.RSSI());
  }
  cJSON* request = readFrame(100);
  if (request) {
    if (!isType(request, "start") || !runTrial(request)) linkClient.stop();
    cJSON_Delete(request);
  }
  delay(1);
}
