/*
 * Virtual EEG headset — classic ESP32 (WROOM-32).
 *
 * Serves a dashboard with five buttons over WiFi. Pressing one streams the
 * matching .edf snippet, byte for byte, over Bluetooth Classic (SPP) to the
 * Raspberry Pi. The Pi writes the bytes to a file and runs the classifier it
 * already has — the payload is a plain EDF, so nothing on the Pi changes.
 *
 * Wire frame (one per button press, on a persistent SPP connection):
 *
 *     "EDF1" | class_id u8 | length u32 little-endian | <length bytes of .edf>
 *
 * The length prefix is needed because RFCOMM is a stream: without it the Pi
 * cannot tell where one snippet ends and the next begins.
 *
 * ---------------------------------------------------------------------------
 * Board:            ESP32 Dev Module (WROOM-32)
 * Partition Scheme: "No OTA (2MB APP / 2MB SPIFFS)"
 *                   The default 1.2MB app is too small once Bluedroid + WiFi +
 *                   WebServer are linked, and the 190KB "Minimal SPIFFS" data
 *                   partition is too small for 212KB of snippets.
 * Upload data/:     Tools -> "ESP32 Sketch Data Upload" (LittleFS)
 * ---------------------------------------------------------------------------
 *
 * NOTE: this sketch has not been compiled or flashed here — no board was
 * attached. The protocol it speaks is exercised by pi_receive.py and
 * host_send.py, which round-trip the same frames.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <LittleFS.h>
#include "BluetoothSerial.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error "Bluetooth Classic is off. Enable it, or use an original ESP32 — the S3/C3 have BLE only."
#endif

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
static const char *WIFI_SSID = "YOUR_WIFI";
static const char *WIFI_PASS = "YOUR_PASSWORD";
static const char *BT_NAME   = "ESP32-EEG-Headset";  // the Pi connects to this

// Optional physical buttons, one per command. Set to -1 to disable a pin.
// Wired to GND, using the internal pull-ups (pressed == LOW).
#define ENABLE_GPIO_BUTTONS 1
static const int BUTTON_PIN[5] = {32, 33, 25, 26, 27};
static const uint32_t DEBOUNCE_MS = 250;

// ---------------------------------------------------------------------------
static const uint8_t N_SNIPPETS = 5;
static const char *SNIPPET_PATH[N_SNIPPETS] = {
    "/s0.edf", "/s1.edf", "/s2.edf", "/s3.edf", "/s4.edf"};
static const char COMMAND_CHAR[N_SNIPPETS] = {'S', 'O', 'C', 'L', 'R'};

static const size_t CHUNK = 1024;      // never buffer a whole snippet in RAM
static const uint32_t TX_TIMEOUT_MS = 15000;

BluetoothSerial SerialBT;
WebServer server(80);

static String lastStatus = "idle";
static uint32_t lastSentBytes = 0;
static uint32_t lastPressMs[N_SNIPPETS] = {0};

// ---------------------------------------------------------------------------
// Send one snippet over SPP
// ---------------------------------------------------------------------------
static bool sendSnippet(uint8_t id) {
  if (id >= N_SNIPPETS) {
    lastStatus = "bad snippet id";
    return false;
  }
  if (!SerialBT.hasClient()) {
    lastStatus = "no Pi connected over Bluetooth";
    return false;
  }
  File f = LittleFS.open(SNIPPET_PATH[id], "r");
  if (!f) {
    lastStatus = String("missing ") + SNIPPET_PATH[id];
    return false;
  }

  const uint32_t len = f.size();
  uint8_t header[9] = {'E', 'D', 'F', '1', id,
                       (uint8_t)(len), (uint8_t)(len >> 8),
                       (uint8_t)(len >> 16), (uint8_t)(len >> 24)};
  SerialBT.write(header, sizeof(header));

  uint8_t buf[CHUNK];
  uint32_t sent = 0;
  const uint32_t started = millis();
  while (sent < len) {
    const size_t want = (len - sent) < CHUNK ? (size_t)(len - sent) : CHUNK;
    const size_t n = f.read(buf, want);
    if (n == 0) break;                       // short read: file truncated
    size_t written = 0;
    while (written < n) {
      // write() returns 0 when the SPP tx buffer is full; yield and retry
      // rather than spin, or the WiFi/BT stacks starve.
      const size_t k = SerialBT.write(buf + written, n - written);
      if (k == 0) {
        if (millis() - started > TX_TIMEOUT_MS || !SerialBT.hasClient()) {
          f.close();
          lastStatus = "link stalled mid-snippet";
          return false;
        }
        delay(2);
      }
      written += k;
    }
    sent += n;
  }
  f.close();

  if (sent != len) {
    lastStatus = "short read from LittleFS";
    return false;
  }
  lastSentBytes = sent;
  lastStatus = String("sent ") + SNIPPET_PATH[id] + " (" + sent + " B), expecting " +
               COMMAND_CHAR[id];
  Serial.println(lastStatus);
  return true;
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------
static void handleSend() {
  if (!server.hasArg("id")) {
    server.send(400, "application/json", "{\"error\":\"missing id\"}");
    return;
  }
  const int id = server.arg("id").toInt();
  const bool ok = sendSnippet((uint8_t)id);
  String body = String("{\"ok\":") + (ok ? "true" : "false") +
                ",\"status\":\"" + lastStatus + "\",\"bytes\":" + lastSentBytes + "}";
  server.send(ok ? 200 : 503, "application/json", body);
}

static void handleStatus() {
  String body = String("{\"bt\":") + (SerialBT.hasClient() ? "true" : "false") +
                ",\"name\":\"" + BT_NAME + "\",\"status\":\"" + lastStatus +
                "\",\"ip\":\"" + WiFi.localIP().toString() + "\"}";
  server.send(200, "application/json", body);
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  if (!LittleFS.begin(false)) {
    Serial.println("LittleFS mount failed — did you run 'ESP32 Sketch Data Upload'?");
    while (true) delay(1000);
  }
  for (uint8_t i = 0; i < N_SNIPPETS; i++) {
    if (!LittleFS.exists(SNIPPET_PATH[i])) {
      Serial.printf("missing %s on LittleFS\n", SNIPPET_PATH[i]);
    }
  }

#if ENABLE_GPIO_BUTTONS
  for (uint8_t i = 0; i < N_SNIPPETS; i++)
    if (BUTTON_PIN[i] >= 0) pinMode(BUTTON_PIN[i], INPUT_PULLUP);
#endif

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\ndashboard: http://%s/\n", WiFi.localIP().toString().c_str());

  // WiFi and Bluetooth Classic share one 2.4 GHz radio and a tight heap. It
  // works, but keep buffers small — hence the 1 KB streaming chunk above.
  SerialBT.begin(BT_NAME);
  Serial.printf("Bluetooth SPP up as \"%s\"; pair the Pi, then connect to channel 1\n", BT_NAME);
  Serial.printf("free heap: %u B\n", ESP.getFreeHeap());

  server.serveStatic("/", LittleFS, "/index.html");
  server.serveStatic("/snippets.json", LittleFS, "/snippets.json");
  server.on("/api/send", HTTP_GET, handleSend);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.begin();
}

void loop() {
  server.handleClient();

#if ENABLE_GPIO_BUTTONS
  const uint32_t now = millis();
  for (uint8_t i = 0; i < N_SNIPPETS; i++) {
    if (BUTTON_PIN[i] < 0) continue;
    if (digitalRead(BUTTON_PIN[i]) == LOW && now - lastPressMs[i] > DEBOUNCE_MS) {
      lastPressMs[i] = now;
      sendSnippet(i);
    }
  }
#endif
}
