// =============================================================================
//  uart_link.cpp — Contract A listener + fail-safe.
// =============================================================================

#include "uart_link.h"

#include <Arduino.h>
#include "config.h"
#include "contracts.h"
#include "dispatch.h"

static char   line[UART_LINE_MAX];
static size_t lineLen = 0;

// Where Contract A arrives. Serial IS the USB bridge on this board, so a single
// USB cable from the Pi lands here; Serial2 is the three-jumper GPIO link.
// Everything below reads `linkPort` and does not care which one it is.
// (Not `link` -- that is POSIX link(2), pulled in via unistd.h.)
#if UART_USE_USB
static HardwareSerial& linkPort = Serial;
#else
static HardwareSerial& linkPort = Serial2;
#endif

void uartLinkBegin() {
#if UART_USE_USB
    // Serial was already opened at UART_BAUD by setup(); opening it again would
    // just churn the port the Pi is talking on. The Pi's bytes and our own debug
    // prints share this cable in opposite directions -- full duplex, no conflict.
    Serial.printf("[LINK-A] listening on the USB serial port @ %d "
                  "(one cable from the Pi; /dev/ttyUSB0 on its side)\n", UART_BAUD);
#else
    Serial2.begin(UART_BAUD, SERIAL_8N1, UART_RX_PIN, UART_TX_PIN);
    Serial.printf("[LINK-A] UART2 up @ %d (RX=%d TX=%d)\n",
                  UART_BAUD, UART_RX_PIN, UART_TX_PIN);
#endif
}

static void handleLine() {
    line[lineLen] = '\0';
    lineLen = 0;
    // trim a trailing CR from Windows-style senders
    for (char* p = line; *p; p++)
        if (*p == '\r') { *p = '\0'; break; }
    if (!line[0]) return;

    if (!isValidLabel(line)) {
        Serial.printf("[LINK-A] unknown label ignored: '%s'\n", line);
        return;
    }
    applyLabel(line);
}

void uartLinkUpdate() {
    while (linkPort.available()) {
        const char c = (char)linkPort.read();
        if (c == '\n') {
            handleLine();
        } else if (lineLen < UART_LINE_MAX - 1) {
            line[lineLen++] = c;
        } else {
            lineLen = 0;   // oversized line: drop it and resync at next newline
        }
    }

    // Fail-safe: no valid label for FAILSAFE_TIMEOUT_MS -> flag the link down.
    // Per config.h we HOLD position (no motion command), so nothing to move.
    if (g_status.linkAConnected &&
        millis() - g_status.lastLabelMs > FAILSAFE_TIMEOUT_MS) {
        g_status.linkAConnected = false;
        Serial.println("[LINK-A] fail-safe: no signal, holding position");
    }
}
