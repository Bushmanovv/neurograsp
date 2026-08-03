// =============================================================================
//  InMoov EEG Prosthetic Hand — ESP32 firmware
//
//  Layers 0-4 online:
//    0  scaffold + contracts + persistent config          (store.*)
//    1  GPIO servo core (ESP32Servo), smooth moves, built-ins  (servos.*)
//       UART label listener (Contract A) + fail-safe hold  (uart_link.*)
//       battery monitor                                    (battery.*)
//    2  WiFi soft-AP + REST API (Contract B)               (webserver.*)
//    3  WebSocket telemetry push                           (webserver.*)
//    4  static dashboard served from LittleFS (gzipped)    (webserver.*)
//
//  Cue path : Pi --UART--> uart_link --> dispatch --> servos
//  App path : phone --HTTP/WS--> webserver --> dispatch --> servos
//  Both funnel through dispatch.cpp so they can never disagree, and both
//  update the one g_status snapshot the dashboard renders.
//
//  See CONTRACTS.md for the UART + Web API contracts and data models.
// =============================================================================

#include <Arduino.h>
#include <LittleFS.h>

#include "config.h"
#include "battery.h"
#include "servos.h"
#include "store.h"
#include "sync.h"
#include "uart_link.h"
#include "webserver.h"

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.println("=============================================");
    Serial.printf ("  InMoov Hand controller  fw %s\n", FW_VERSION);
    Serial.println("  Layers 0-4 — servos + link + web");
    Serial.println("=============================================");

    stateSyncBegin();  // create the shared-state mutex BEFORE anything locks it

    if (!LittleFS.begin(true)) {
        Serial.println("[FS] FATAL: LittleFS mount failed");
        return;
    }
    Serial.printf("[FS] LittleFS mounted (%u / %u bytes used)\n",
                  (unsigned)LittleFS.usedBytes(), (unsigned)LittleFS.totalBytes());

    storeBegin();      // load mappings + poses (self-heals defaults)
    servosBegin();     // attach servos; hand to relax
    batteryBegin();    // first ADC read
    uartLinkBegin();   // Serial2 label listener + fail-safe
    webBegin();        // AP + REST + WebSocket + static files

    Serial.println("[OK] system ready.");
}

void loop() {
    uartLinkUpdate();  // drain RX, run fail-safe
    servosUpdate();    // step the smooth interpolation
    batteryUpdate();   // periodic sample
    webUpdate();       // WS housekeeping + telemetry push
    storeFlush();      // persist any pending mapping/pose changes (off the TCP task)
}
