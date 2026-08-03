#pragma once
// =============================================================================
//  webserver.h — Layers 2-4: WiFi AP + REST API (Contract B) + WebSocket
//  telemetry + static file serving from LittleFS (gzip-aware).
//  The phone joins the AP and loads the dashboard entirely from the device.
// =============================================================================

void webBegin();
void webUpdate();   // call every loop(): housekeeps WS clients + pushes telemetry
