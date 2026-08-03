#pragma once
// =============================================================================
//  battery.h — battery voltage via divider on BATT_ADC_PIN.
//  Smoothed with an EMA; results land in g_status.batteryV / batteryPct.
// =============================================================================

void batteryBegin();
void batteryUpdate();   // call every loop(); samples every ~500 ms
