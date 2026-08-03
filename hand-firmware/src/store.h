#pragma once
// =============================================================================
//  store.h — persistent app data: the mapping table + saved poses.
//  RAM copies are the working set; every change is written back to LittleFS
//  (/mappings.json, /poses.json) so it survives a power cycle.
// =============================================================================

#include <Arduino.h>
#include <ArduinoJson.h>
#include "config.h"

#define POSE_NAME_MAX 32
#define POSES_MAX     24        // bounds RAM + JSON document size

struct Pose {
    char    name[POSE_NAME_MAX];
    uint8_t angles[SERVO_COUNT];
};

// Ensure both files exist (write defaults if missing OR corrupt) and load them
// into RAM.
bool storeBegin();

// Persist any pending mapping/pose changes to LittleFS. Called from loop() so
// the flash writes happen on the loop task, never inside an async web handler.
void storeFlush();

// ---- mappings (Contract A label -> action) ----
const char* mappingFor(const char* label);            // nullptr if unknown label
bool        setMappings(JsonObjectConst obj);         // replace + persist
void        mappingsToJson(JsonObject out);

// ---- poses ----
size_t      poseCount();
const Pose* poseAt(size_t i);
const Pose* findPose(const char* name);
bool        upsertPose(const char* name, const uint8_t angles[SERVO_COUNT]);
bool        deletePose(const char* name);
void        posesToJson(JsonArray out);
