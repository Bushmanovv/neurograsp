#pragma once
// =============================================================================
//  sync.h — one recursive mutex guarding all shared mutable state.
//
//  ESPAsyncWebServer/AsyncTCP run every HTTP + WebSocket handler on the
//  "async_tcp" task, a DIFFERENT FreeRTOS task from the Arduino loopTask that
//  runs uartLinkUpdate()/servosUpdate()/batteryUpdate(). Both touch the same
//  data (g_status, the servo interpolation arrays, the poses[]/mappings[]
//  tables). Every access to that shared state — on either task — is wrapped in
//  a StateLock so a web write can never tear a value a cue read is using
//  (e.g. deletePose() shifting the array mid-lookup).
//
//  The mutex is RECURSIVE so nested locked calls on the same task are fine
//  (applyAction -> servosSetTargets -> servoSetTarget all lock).
//
//  Critical sections are kept short (RAM only). Slow work — LittleFS writes —
//  is deferred to the loop task via storeFlush(), never held under the lock.
// =============================================================================

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

void              stateSyncBegin();   // create the mutex; call FIRST in setup()
SemaphoreHandle_t stateMutex();

// RAII scoped lock. `StateLock lk;` locks for the rest of the enclosing scope.
struct StateLock {
    StateLock()  { xSemaphoreTakeRecursive(stateMutex(), portMAX_DELAY); }
    ~StateLock() { xSemaphoreGiveRecursive(stateMutex()); }
    StateLock(const StateLock&) = delete;
    StateLock& operator=(const StateLock&) = delete;
};
