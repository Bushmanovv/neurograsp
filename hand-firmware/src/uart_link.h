#pragma once
// =============================================================================
//  uart_link.h — Link A: Raspberry Pi -> ESP32 label stream (Contract A).
//  One lower_snake_case label per newline-terminated line on Serial2.
//  Unknown labels are logged and ignored. Includes the fail-safe watchdog:
//  if no VALID label arrives within FAILSAFE_TIMEOUT_MS the link is flagged
//  down and the hand HOLDS its position (no motion command is issued).
// =============================================================================

void uartLinkBegin();
void uartLinkUpdate();   // call every loop(): drains RX + runs the fail-safe
