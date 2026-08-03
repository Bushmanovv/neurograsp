// =============================================================================
//  dispatch.cpp — action resolution shared by UART (cues) and the web API.
//  Also owns the one recursive mutex that guards all shared mutable state
//  (see sync.h).
// =============================================================================

#include "dispatch.h"
#include "contracts.h"   // REST_LABEL: the heartbeat is not a gesture
#include "servos.h"
#include "store.h"
#include "sync.h"

SystemStatus g_status;   // the one global status snapshot (declared in status.h)

// ---- shared-state mutex (sync.h) -------------------------------------------
static SemaphoreHandle_t s_mux = nullptr;

void stateSyncBegin() {
    if (!s_mux) s_mux = xSemaphoreCreateRecursiveMutex();
}
SemaphoreHandle_t stateMutex() {
    if (!s_mux) stateSyncBegin();   // safety net; setup() should call it first
    return s_mux;
}

// ---- action dispatch --------------------------------------------------------
bool applyAction(const char* action, CmdSource source) {
    if (!action || !*action) return false;

    // Held across the pose lookup + servo retarget + status write so a
    // concurrent deletePose()/upsertPose() can't move the Pose out from under
    // the pointer we resolve. Recursive: servosSetTargets() re-locks.
    StateLock lk;

    const uint8_t* angles = builtinActionAngles(action);
    bool isPose = false;
    if (!angles) {
        const Pose* p = findPose(action);
        if (!p) return false;
        angles = p->angles;
        isPose = true;
    }

    servosSetTargets(angles);
    g_status.source = source;
    strlcpy(g_status.lastAction, action, sizeof(g_status.lastAction));
    strlcpy(g_status.activePose, isPose ? action : "", sizeof(g_status.activePose));
    return true;
}

void applyLabel(const char* label) {
    StateLock lk;

    // Say so the first time the Pi is heard (and again after a fail-safe drop).
    // Without this the link is silent when it works -- `rest` moves nothing and
    // logs nothing -- so a swapped TX/RX pair would look exactly like a healthy
    // idle link. One line here turns bring-up from guesswork into a yes/no.
    if (!g_status.linkAConnected)
        Serial.printf("[LINK-A] link up (first label: '%s')\n", label);

    g_status.lastLabelMs    = millis();
    g_status.linkAConnected = true;
    strlcpy(g_status.lastLabel, label, sizeof(g_status.lastLabel));

    // The heartbeat keeps the link alive; it does not move the hand.
    //
    // The Pi sends `rest` every 1.2 s whenever it has nothing to report -- which
    // includes ~1.2 s after every confirmed gesture. Dispatching it as a motion
    // (the default mapping is rest -> relax, and relax is a real move to
    // {20,20,20,20,20}) would re-open the fingers a second after each command:
    // the hand could never hold a grasp, which is the one thing it exists to do.
    //
    // Doing nothing here is also exactly what the fail-safe does when the link
    // dies (uart_link.cpp: HOLD position), so a live-but-idle link and a dead one
    // now agree: the hand keeps the pose it was last given, until it is given a
    // new one. Use another gesture -- or the app's relax button -- to open it.
    if (strcmp(label, REST_LABEL) == 0) return;

    const char* action = mappingFor(label);
    if (!action || !applyAction(action, CmdSource::Cue))
        Serial.printf("[LINK-A] label '%s' has no usable action ('%s')\n",
                      label, action ? action : "?");
}
