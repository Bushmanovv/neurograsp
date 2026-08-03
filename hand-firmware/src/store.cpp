// =============================================================================
//  store.cpp — mappings + poses persistence (LittleFS + ArduinoJson).
//
//  RAM copies are the working set and are the source of truth. Changes are
//  flagged dirty and written back to LittleFS by storeFlush() on the loop task
//  (never from an async web handler). All access to the RAM tables is guarded
//  by StateLock (sync.h) because reads come from the async web task while
//  writes come from both tasks.
// =============================================================================

#include "store.h"

#include <LittleFS.h>
#include "contracts.h"
#include "sync.h"

// Defaults written on first boot — keep in sync with data/mappings.json and
// data/poses.json (the FS image ships the same content).
static const char DEFAULT_MAPPINGS[] PROGMEM = R"json({
  "single_blink": "open_hand",
  "double_blink": "pinch",
  "clinch": "close_fist",
  "bruxism_left": "wrist_left",
  "bruxism_right": "wrist_right",
  "rest": "relax"
})json";

static const char DEFAULT_POSES[] PROGMEM = R"json({
  "poses": [
    { "name": "ok_sign", "angles": [120, 100, 10, 10, 10, 90] }
  ]
})json";

// RAM working set. mappings[i] belongs to VALID_LABELS[i].
static char   mappings[VALID_LABELS_COUNT][POSE_NAME_MAX];
static Pose   poses[POSES_MAX];
static size_t nPoses = 0;

// Deferred-write flags; storeFlush() (loop task) drains them to LittleFS.
static volatile bool mappingsDirty = false;
static volatile bool posesDirty    = false;

// -----------------------------------------------------------------------------
static bool writeDefaults(const char* path, const char* defaults) {
    File f = LittleFS.open(path, "w");
    if (!f) { Serial.printf("[STORE] ERROR: cannot write %s\n", path); return false; }
    f.print(defaults);
    f.close();
    return true;
}

static bool ensureFile(const char* path, const char* defaults) {
    if (LittleFS.exists(path)) return true;
    if (!writeDefaults(path, defaults)) return false;
    Serial.printf("[STORE] %s missing -> wrote defaults\n", path);
    return true;
}

static int labelIndex(const char* label) {
    for (size_t i = 0; i < VALID_LABELS_COUNT; i++)
        if (strcmp(label, VALID_LABELS[i]) == 0) return (int)i;
    return -1;
}

static bool writeJsonFile(const char* path, const JsonDocument& doc) {
    File f = LittleFS.open(path, "w");
    if (!f) { Serial.printf("[STORE] ERROR: cannot write %s\n", path); return false; }
    serializeJson(doc, f);
    f.close();
    return true;
}

// -----------------------------------------------------------------------------
static bool loadMappings() {
    File f = LittleFS.open(PATH_MAPPINGS, "r");
    if (!f) return false;
    JsonDocument doc;
    if (deserializeJson(doc, f)) { f.close(); return false; }
    f.close();
    StateLock lk;
    for (size_t i = 0; i < VALID_LABELS_COUNT; i++) {
        const char* v = doc[VALID_LABELS[i]] | "relax";
        strlcpy(mappings[i], v, POSE_NAME_MAX);
    }
    return true;
}

static bool loadPoses() {
    File f = LittleFS.open(PATH_POSES, "r");
    if (!f) return false;
    JsonDocument doc;
    if (deserializeJson(doc, f)) { f.close(); return false; }
    f.close();
    StateLock lk;
    nPoses = 0;
    for (JsonObject p : doc["poses"].as<JsonArray>()) {
        if (nPoses >= POSES_MAX) break;
        const char* name = p["name"] | "";
        JsonArray a = p["angles"].as<JsonArray>();
        if (!*name || a.size() != SERVO_COUNT) continue;
        strlcpy(poses[nPoses].name, name, POSE_NAME_MAX);
        for (size_t i = 0; i < SERVO_COUNT; i++)
            poses[nPoses].angles[i] = constrain(a[i].as<int>(), SERVO_ANGLE_MIN, SERVO_ANGLE_MAX);
        nPoses++;
    }
    return true;
}

static bool persistMappings() {
    JsonDocument doc;
    mappingsToJson(doc.to<JsonObject>());   // reads RAM under its own lock
    return writeJsonFile(PATH_MAPPINGS, doc);
}

static bool persistPoses() {
    JsonDocument doc;
    posesToJson(doc["poses"].to<JsonArray>());
    return writeJsonFile(PATH_POSES, doc);
}

// -----------------------------------------------------------------------------
bool storeBegin() {
    ensureFile(PATH_MAPPINGS, DEFAULT_MAPPINGS);
    ensureFile(PATH_POSES, DEFAULT_POSES);

    // Self-heal: a file can EXIST but be corrupt (e.g. power loss mid-write).
    // If it won't parse, overwrite it with defaults and reload — otherwise the
    // tables stay empty and every cue silently no-ops forever.
    bool okM = loadMappings();
    if (!okM) {
        Serial.printf("[STORE] %s unreadable -> rewriting defaults\n", PATH_MAPPINGS);
        writeDefaults(PATH_MAPPINGS, DEFAULT_MAPPINGS);
        okM = loadMappings();
    }
    bool okP = loadPoses();
    if (!okP) {
        Serial.printf("[STORE] %s unreadable -> rewriting defaults\n", PATH_POSES);
        writeDefaults(PATH_POSES, DEFAULT_POSES);
        okP = loadPoses();
    }

    Serial.printf("[STORE] loaded %u mapping(s), %u pose(s)%s\n",
                  (unsigned)VALID_LABELS_COUNT, (unsigned)nPoses,
                  (okM && okP) ? "" : "  (with errors)");
    return okM && okP;
}

void storeFlush() {
    bool m, p;
    { StateLock lk; m = mappingsDirty; mappingsDirty = false;
                    p = posesDirty;    posesDirty    = false; }
    if (m) persistMappings();   // flash writes on the loop task, outside the lock
    if (p) persistPoses();
}

const char* mappingFor(const char* label) {
    StateLock lk;
    const int i = labelIndex(label);
    return i < 0 ? nullptr : mappings[i];
}

bool setMappings(JsonObjectConst obj) {
    StateLock lk;
    for (JsonPairConst kv : obj) {
        const int i = labelIndex(kv.key().c_str());
        if (i < 0) continue;                       // unknown labels are ignored
        const char* v = kv.value().as<const char*>();
        if (v && *v) strlcpy(mappings[i], v, POSE_NAME_MAX);
    }
    mappingsDirty = true;                          // persisted by storeFlush()
    return true;
}

void mappingsToJson(JsonObject out) {
    StateLock lk;
    for (size_t i = 0; i < VALID_LABELS_COUNT; i++)
        out[VALID_LABELS[i]] = mappings[i];
}

size_t poseCount() { StateLock lk; return nPoses; }
const Pose* poseAt(size_t i) { StateLock lk; return i < nPoses ? &poses[i] : nullptr; }

const Pose* findPose(const char* name) {
    if (!name) return nullptr;
    StateLock lk;
    for (size_t i = 0; i < nPoses; i++)
        if (strcmp(poses[i].name, name) == 0) return &poses[i];
    return nullptr;
}

bool upsertPose(const char* name, const uint8_t angles[SERVO_COUNT]) {
    if (!name || !*name || strlen(name) >= POSE_NAME_MAX) return false;
    StateLock lk;
    Pose* slot = const_cast<Pose*>(findPose(name));
    if (!slot) {
        if (nPoses >= POSES_MAX) { Serial.println("[STORE] pose limit reached"); return false; }
        slot = &poses[nPoses++];
        strlcpy(slot->name, name, POSE_NAME_MAX);
    }
    memcpy(slot->angles, angles, SERVO_COUNT);
    posesDirty = true;
    return true;
}

bool deletePose(const char* name) {
    StateLock lk;
    for (size_t i = 0; i < nPoses; i++) {
        if (strcmp(poses[i].name, name) != 0) continue;
        for (size_t j = i + 1; j < nPoses; j++) poses[j - 1] = poses[j];
        nPoses--;
        // Any mapping that pointed at this pose now dangles -> rebind to "relax"
        // so the cue keeps doing something safe instead of silently no-op'ing.
        for (size_t k = 0; k < VALID_LABELS_COUNT; k++)
            if (strcmp(mappings[k], name) == 0) {
                strlcpy(mappings[k], "relax", POSE_NAME_MAX);
                mappingsDirty = true;
            }
        posesDirty = true;
        return true;
    }
    return false;
}

void posesToJson(JsonArray out) {
    StateLock lk;
    for (size_t i = 0; i < nPoses; i++) {
        JsonObject p = out.add<JsonObject>();
        p["name"] = poses[i].name;
        JsonArray a = p["angles"].to<JsonArray>();
        for (size_t j = 0; j < SERVO_COUNT; j++) a.add(poses[i].angles[j]);
    }
}
