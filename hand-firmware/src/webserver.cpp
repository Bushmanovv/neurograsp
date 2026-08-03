// =============================================================================
//  webserver.cpp — WiFi AP, REST API, WebSocket telemetry, static serving.
//
//  Contract B endpoints (all JSON):
//    GET    /api/state              full snapshot: status + mappings + poses
//    GET    /api/mappings           label -> action table
//    POST   /api/mappings           replace mappings         {label:action,...}
//    GET    /api/poses              saved poses
//    POST   /api/poses              add/replace a pose        {name,angles[6]}
//    DELETE /api/poses/<name>       delete a pose
//    POST   /api/pose/apply         apply a saved pose        {name}
//    POST   /api/servo              nudge one channel         {channel,angle}
//    POST   /api/relax              open/relax the hand
//    WS     /ws                     server pushes {type:"status",...} @ ~6 Hz
//
//  Static files are served from LittleFS; prep_fs.py gzips them, and
//  ESPAsyncWebServer transparently serves `foo.gz` for a request to `foo`.
//
//  Handlers run on the async_tcp task, so every read of the shared status /
//  mappings / poses tables is wrapped in StateLock (sync.h), and mutations go
//  through store.*/dispatch.* which flag their writes for storeFlush() to
//  persist on the loop task (no LittleFS writes on this task).
// =============================================================================

#include "webserver.h"

#include <Arduino.h>
#include <WiFi.h>
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <ESPAsyncWebServer.h>

#include "config.h"
#include "contracts.h"   // isValidLabel() -- Contract A also arrives over WiFi now
#include "dispatch.h"
#include "servos.h"
#include "store.h"
#include "sync.h"

static AsyncWebServer server(80);
static AsyncWebSocket ws("/ws");

// -----------------------------------------------------------------------------
//  status serialization (shared by /api/state and the WS push)
// -----------------------------------------------------------------------------
static void writeStatus(JsonObject o) {
    StateLock lk;   // consistent snapshot of g_status + the live servo angles
    o["battery_pct"]     = g_status.batteryPct;
    o["battery_v"]       = g_status.batteryV;
    o["linkA_connected"] = g_status.linkAConnected;
    o["last_label"]      = g_status.lastLabel;
    o["last_action"]     = g_status.lastAction;
    o["active_pose"]     = g_status.activePose;
    o["source"]          = cmdSourceName(g_status.source);
    JsonArray a = o["servo_angles"].to<JsonArray>();
    const uint8_t* cur = servosCurrent();
    for (size_t i = 0; i < SERVO_COUNT; i++) a.add(cur[i]);
}

static size_t statusJson(String& out) {
    JsonDocument doc;
    JsonObject o = doc.to<JsonObject>();
    o["type"] = "status";
    writeStatus(o);
    return serializeJson(doc, out);
}

// -----------------------------------------------------------------------------
//  small helpers
// -----------------------------------------------------------------------------
static void sendJson(AsyncWebServerRequest* req, int code, const JsonDocument& doc) {
    auto* res = req->beginResponseStream("application/json");
    res->setCode(code);
    serializeJson(doc, *res);
    req->send(res);
}
static void ok(AsyncWebServerRequest* req)   { req->send(200, "application/json", "{\"ok\":true}"); }
static void bad(AsyncWebServerRequest* req, const char* msg) {
    req->send(400, "application/json", String("{\"ok\":false,\"error\":\"") + msg + "\"}");
}

// Percent-decode a path segment (%XX and '+') so a pose named with spaces etc.
// matches what was stored. The dashboard sends encodeURIComponent(name).
static String urlDecode(const String& s) {
    String out; out.reserve(s.length());
    auto hex = [](char h) -> int {
        if (h >= '0' && h <= '9') return h - '0';
        h |= 0x20; return (h >= 'a' && h <= 'f') ? h - 'a' + 10 : -1;
    };
    for (size_t i = 0; i < s.length(); i++) {
        const char c = s[i];
        if (c == '+') { out += ' '; }
        else if (c == '%' && i + 2 < s.length()) {
            const int hi = hex(s[i + 1]), lo = hex(s[i + 2]);
            if (hi >= 0 && lo >= 0) { out += (char)((hi << 4) | lo); i += 2; }
            else out += c;
        } else out += c;
    }
    return out;
}

// Body handler wrapper: buffer the chunked JSON body, parse once complete.
// The buffer is malloc'd (NOT new) so that if the client aborts mid-upload,
// ESPAsyncWebServer's free(_tempObject) on request teardown is correct and
// leaks nothing; on the normal path we free it ourselves.
typedef std::function<void(AsyncWebServerRequest*, JsonDocument&)> JsonBodyFn;
static ArBodyHandlerFunction jsonBody(JsonBodyFn fn) {
    return [fn](AsyncWebServerRequest* req, uint8_t* data, size_t len,
                size_t index, size_t total) {
        if (index == 0) {
            req->_tempObject = malloc(total + 1);
            if (!req->_tempObject) { req->send(500, "application/json",
                                     "{\"ok\":false,\"error\":\"oom\"}"); return; }
        }
        if (!req->_tempObject) return;             // earlier OOM on this request
        char* buf = (char*)req->_tempObject;
        memcpy(buf + index, data, len);
        if (index + len != total) return;

        buf[total] = '\0';
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, buf, total);
        free(buf); req->_tempObject = nullptr;
        if (err) { bad(req, "invalid json"); return; }
        fn(req, doc);
    };
}

// -----------------------------------------------------------------------------
//  routes
// -----------------------------------------------------------------------------
static void routeState(AsyncWebServerRequest* req) {
    JsonDocument doc;
    JsonObject root = doc.to<JsonObject>();
    StateLock lk;   // atomic snapshot across status + mappings + poses
    writeStatus(root["status"].to<JsonObject>());
    mappingsToJson(root["mappings"].to<JsonObject>());
    posesToJson(root["poses"].to<JsonArray>());
    sendJson(req, 200, doc);
}

static void routeGetMappings(AsyncWebServerRequest* req) {
    JsonDocument doc;
    mappingsToJson(doc.to<JsonObject>());
    sendJson(req, 200, doc);
}

static void routeGetPoses(AsyncWebServerRequest* req) {
    JsonDocument doc;
    posesToJson(doc["poses"].to<JsonArray>());
    sendJson(req, 200, doc);
}

static bool anglesFromJson(JsonArrayConst a, uint8_t out[SERVO_COUNT]) {
    if (a.size() != SERVO_COUNT) return false;
    for (size_t i = 0; i < SERVO_COUNT; i++)
        out[i] = constrain(a[i].as<int>(), SERVO_ANGLE_MIN, SERVO_ANGLE_MAX);
    return true;
}

void webBegin() {
    // --- WiFi soft-AP (no internet; assets are local) ---
    WiFi.mode(WIFI_AP);
    const bool up = WiFi.softAP(AP_SSID, AP_PASSWORD[0] ? AP_PASSWORD : nullptr,
                                AP_CHANNEL, false, AP_MAX_CLIENTS);
    Serial.printf("[WEB] AP '%s' %s, http://%s/\n", AP_SSID,
                  up ? "up" : "FAILED", WiFi.softAPIP().toString().c_str());

    // --- WebSocket: on connect, send one snapshot so the client is current ---
    ws.onEvent([](AsyncWebSocket*, AsyncWebSocketClient* client,
                  AwsEventType type, void*, uint8_t*, size_t) {
        if (type == WS_EVT_CONNECT) {
            String s; statusJson(s);
            client->text(s);
        }
    });
    server.addHandler(&ws);

    // --- REST: reads ---
    server.on("/api/state",    HTTP_GET, routeState);
    server.on("/api/mappings", HTTP_GET, routeGetMappings);
    server.on("/api/poses",    HTTP_GET, routeGetPoses);

    // --- REST: writes ---
    server.on("/api/mappings", HTTP_POST, [](AsyncWebServerRequest*){}, nullptr,
        jsonBody([](AsyncWebServerRequest* req, JsonDocument& doc) {
            if (!doc.is<JsonObject>()) { bad(req, "expected object"); return; }
            setMappings(doc.as<JsonObject>());
            ok(req);
        }));

    server.on("/api/poses", HTTP_POST, [](AsyncWebServerRequest*){}, nullptr,
        jsonBody([](AsyncWebServerRequest* req, JsonDocument& doc) {
            const char* name = doc["name"] | "";
            uint8_t angles[SERVO_COUNT];
            if (!*name || !anglesFromJson(doc["angles"].as<JsonArrayConst>(), angles)) {
                bad(req, "need name + angles[6]"); return;
            }
            if (!upsertPose(name, angles)) { bad(req, "pose limit or bad name"); return; }
            ok(req);
        }));

    server.on("/api/pose/apply", HTTP_POST, [](AsyncWebServerRequest*){}, nullptr,
        jsonBody([](AsyncWebServerRequest* req, JsonDocument& doc) {
            const char* name = doc["name"] | "";
            if (!applyAction(name, CmdSource::Manual)) { bad(req, "unknown pose"); return; }
            ok(req);
        }));

    server.on("/api/servo", HTTP_POST, [](AsyncWebServerRequest*){}, nullptr,
        jsonBody([](AsyncWebServerRequest* req, JsonDocument& doc) {
            if (!doc["channel"].is<int>() || !doc["angle"].is<int>()) { bad(req, "need channel+angle"); return; }
            const int ch = doc["channel"], ang = doc["angle"];
            if (ch < 0 || ch >= SERVO_COUNT) { bad(req, "bad channel"); return; }
            servoSetTarget((uint8_t)ch, ang);
            { StateLock lk; g_status.source = CmdSource::Manual; }
            ok(req);
        }));

    // Contract A over WiFi. The Pi POSTs the very same label it would have written
    // to the UART; this hands it to applyLabel(), the identical code path the wire
    // uses. So the mappings still decide the action, `lastLabel` and the EEG/link
    // indicator still update, the 3 s fail-safe still arms, and `rest` is still a
    // heartbeat that moves nothing. The transport changed; the contract did not.
    //
    //     curl -X POST http://192.168.4.1/api/cue -H 'Content-Type: application/json' \
    //          -d '{"label":"clinch"}'
    server.on("/api/cue", HTTP_POST, [](AsyncWebServerRequest*){}, nullptr,
        jsonBody([](AsyncWebServerRequest* req, JsonDocument& doc) {
            const char* label = doc["label"] | "";
            if (!isValidLabel(label)) { bad(req, "unknown label"); return; }
            applyLabel(label);
            ok(req);
        }));

    server.on("/api/relax", HTTP_POST, [](AsyncWebServerRequest* req) {
        applyAction("relax", CmdSource::Manual);
        ok(req);
    });

    // DELETE /api/poses/<name>  (name is percent-encoded by the dashboard)
    server.on("^\\/api\\/poses\\/(.+)$", HTTP_DELETE, [](AsyncWebServerRequest* req) {
        String name = urlDecode(req->pathArg(0));
        if (deletePose(name.c_str())) ok(req); else bad(req, "no such pose");
    });

    // --- static: everything else from LittleFS, gzip-aware, SPA index ---
    server.serveStatic("/", LittleFS, "/").setDefaultFile("index.html");
    server.onNotFound([](AsyncWebServerRequest* req) {
        req->send(404, "text/plain", "not found");
    });

    server.begin();
    Serial.println("[WEB] HTTP + WebSocket server started");
}

void webUpdate() {
    ws.cleanupClients();

    // push telemetry to all clients at WS_PUSH_INTERVAL_MS
    static uint32_t lastPush = 0;
    const uint32_t now = millis();
    if (now - lastPush < WS_PUSH_INTERVAL_MS) return;
    lastPush = now;
    if (ws.count() == 0) return;

    String s; statusJson(s);
    ws.textAll(s);
}
