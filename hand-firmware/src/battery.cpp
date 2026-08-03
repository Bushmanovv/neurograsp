// =============================================================================
//  battery.cpp — ADC sampling + smoothing for the 2S LiPo monitor.
// =============================================================================

#include "battery.h"

#include <Arduino.h>
#include "config.h"
#include "status.h"
#include "sync.h"

static const uint32_t SAMPLE_INTERVAL_MS = 500;
static const float    EMA_ALPHA          = 0.2f;   // smooth the noisy ESP32 ADC

static uint32_t lastSampleMs = 0;
static float    emaVolts     = -1.0f;               // <0 = no sample yet

static float readVolts() {
    const int raw = analogRead(BATT_ADC_PIN);
    return (raw / BATT_ADC_MAX) * BATT_ADC_VREF * BATT_DIVIDER_RATIO;
}

// Publish a voltage + derived percentage into the shared status snapshot.
static void publish(float volts) {
    const float pct = (volts - BATT_VOLT_EMPTY) / (BATT_VOLT_FULL - BATT_VOLT_EMPTY) * 100.0f;
    StateLock lk;
    g_status.batteryV   = roundf(volts * 100.0f) / 100.0f;
    g_status.batteryPct = (int)constrain(pct, 0.0f, 100.0f);
}

void batteryBegin() {
    analogSetPinAttenuation(BATT_ADC_PIN, ADC_11db);   // full 0..~3.3 V range
    emaVolts     = readVolts();
    lastSampleMs = millis();
    publish(emaVolts);   // seed g_status now so it never reads 0% at boot
}

void batteryUpdate() {
    const uint32_t now = millis();
    if (now - lastSampleMs < SAMPLE_INTERVAL_MS) return;
    lastSampleMs = now;

    const float v = readVolts();
    emaVolts = (emaVolts < 0) ? v : emaVolts + EMA_ALPHA * (v - emaVolts);
    publish(emaVolts);
}
