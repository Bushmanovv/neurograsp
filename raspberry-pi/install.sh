#!/usr/bin/env bash
# Set up the EEG classifier on this Raspberry Pi and make it start at boot.
#
#   ./install.sh          full install: venv, deps, boot service
#   ./install.sh --check  check only, change nothing
#
# Safe to run more than once. It works out its own paths and username, so there
# is nothing to edit by hand -- the usual way this goes wrong is a stale path in
# a hand-copied unit file, so the unit is generated here instead.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The deploy bundle is this folder plus a copy of the classifier beside it. When
# you rsync only raspberry-pi/ to the Pi, stage the classifier into it first (see
# README_PI.md). Running straight out of a full checkout, the classifier is one
# level up in eeg-classifier/ instead -- so fall back to that.
PROJECT="$HERE/EEG_GRADUATIO_PROJECT"
[ -d "$PROJECT" ] || PROJECT="$(cd "$HERE/.." && pwd)/eeg-classifier"
VENV="$PROJECT/.venv"
PY="$VENV/bin/python"
RUN_USER="$(id -un)"
SERVICE=/etc/systemd/system/eeg-headset.service
CHECK_ONLY=${1:-}

say()  { printf "\n\033[1m== %s\033[0m\n" "$*"; }
ok()   { printf "   \033[32mOK\033[0m    %s\n" "$*"; }
warn() { printf "   \033[33mWARN\033[0m  %s\n" "$*"; }
die()  { printf "   \033[31mFAIL\033[0m  %s\n\n" "$*" >&2; exit 1; }

# --------------------------------------------------------------------------- #
say "1. Checking this machine"

[ "$(uname -s)" = "Linux" ] || die "This installs a systemd service -- run it on the Pi, not on the laptop."
ok "Linux"

if [ "$(uname -m)" = "aarch64" ]; then
    ok "64-bit (aarch64)"
else
    die "$(uname -m) is not aarch64. On 32-bit there are no wheels for scikit-learn/
         scipy/tslearn and the install will try to compile them for an hour.
         Reflash with the 64-bit Raspberry Pi OS image."
fi

command -v python3 >/dev/null || die "python3 not found"
ok "python3 $(python3 -V 2>&1 | cut -d' ' -f2)"

[ -f "$PROJECT/inference.py" ]              || die "no inference.py in $PROJECT"
[ -f "$PROJECT/models/dtw_hybrid_model.pkl" ] || die "no models/dtw_hybrid_model.pkl -- the models did not come across"
ok "classifier + models present"

# --------------------------------------------------------------------------- #
say "2. The UART to the hand (GPIO 14/15)"

# THE PI 5 TRAP: /dev/serial0 is NOT the GPIO header on a Pi 5. The RP1 southbridge
# put the console UART on the dedicated 3-pin debug connector (ttyAMA10), and
# serial0 symlinks to THAT. GPIO 14/15 is ttyAMA0 and only exists once uart0 is
# enabled. Writing to serial0 here would send `clinch` to the debug connector while
# the hand -- wired to pins 8 and 10 -- sits there doing nothing.
HAND_PORT=/dev/ttyAMA0
CONFIG_TXT=/boot/firmware/config.txt
[ -f "$CONFIG_TXT" ] || CONFIG_TXT=/boot/config.txt      # pre-Bookworm layout
NEEDS_REBOOT=0

if grep -qE '^\s*dtparam=uart0(=on)?\s*$' "$CONFIG_TXT" 2>/dev/null; then
    ok "uart0 enabled in $CONFIG_TXT (GPIO 14/15)"
else
    if [ "$CHECK_ONLY" = "--check" ]; then
        warn "uart0 is NOT enabled in $CONFIG_TXT -- $HAND_PORT will not exist.
         The full install adds 'dtparam=uart0=on' for you."
    else
        sudo cp "$CONFIG_TXT" "$CONFIG_TXT.bak-$(date +%Y%m%d%H%M%S)"
        echo "dtparam=uart0=on" | sudo tee -a "$CONFIG_TXT" >/dev/null
        ok "added 'dtparam=uart0=on' to $CONFIG_TXT (backup kept alongside)"
        NEEDS_REBOOT=1
    fi
fi

if [ -e "$HAND_PORT" ]; then
    ok "$HAND_PORT exists (this is the hand's port)"
elif [ "$NEEDS_REBOOT" = "1" ]; then
    warn "$HAND_PORT will appear after the reboot at the end of this script."
else
    warn "$HAND_PORT missing even though uart0 looks enabled -- reboot, then re-run."
fi

if id -nG "$RUN_USER" | tr ' ' '\n' | grep -qx dialout; then
    ok "$RUN_USER is in the 'dialout' group (may write the UART)"
else
    sudo usermod -aG dialout "$RUN_USER"
    ok "added $RUN_USER to 'dialout' (takes effect on reboot)"
    NEEDS_REBOOT=1
fi

# The serial *console* would fight us for the port if it were on the GPIO UART.
if grep -qE 'console=(serial0|ttyAMA0)' /boot/firmware/cmdline.txt /boot/cmdline.txt 2>/dev/null; then
    warn "a serial console is enabled on the GPIO UART -- it will fight the hand for
         the port. Turn it off: sudo raspi-config -> Interface Options -> Serial Port
         -> login shell over serial = No"
else
    ok "no serial console on the GPIO UART"
fi

if [ "$CHECK_ONLY" = "--check" ]; then
    say "--check: nothing was changed."
    exit 0
fi

# --------------------------------------------------------------------------- #
say "3. Building the virtual environment"
# A venv is not relocatable, so it is always built here, on this Pi -- never copied.
if [ -d "$VENV" ]; then
    ok "reusing $VENV"
else
    python3 -m venv "$VENV"
    ok "created $VENV"
fi
"$PY" -m pip install --quiet --upgrade pip setuptools wheel
ok "pip / setuptools / wheel"

say "4. Installing the pinned dependencies (slow: numba + llvmlite build big wheels)"
"$PY" -m pip install -r "$HERE/requirements-pi.txt"
ok "dependencies installed"

# --------------------------------------------------------------------------- #
say "5. Proving the model actually loads on this machine"
# config.py names its models by RELATIVE path, so this must run from the project.
( cd "$PROJECT" && "$PY" - <<'EOF'
import sys
from inference import load_predictor
p = load_predictor("dtw")
print(f"   model loaded: {p.kind}")
EOF
) || die "the model did not load -- see the traceback above"
ok "model loads and the pinned versions match the pickles"

# --------------------------------------------------------------------------- #
say "6. Installing the boot service"
# Generated, not copied: the paths and the username are this machine's real ones.
TMP_UNIT="$(mktemp)"
cat > "$TMP_UNIT" <<EOF
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ). Re-run it to regenerate.
[Unit]
Description=EEG headset classifier (receives .edf snippets, drives the hand)
After=network-online.target
Wants=network-online.target
# Never stop retrying: the default start-limit gives up after 5 restarts in 10 s,
# which is precisely when you need it to keep coming back. ([Unit], not [Service]
# -- systemd ignores it in [Service] and says so in the journal.)
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=dialout
WorkingDirectory=$PROJECT
Environment=EEG_SERIAL_PORT=$HAND_PORT
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $HERE/pi_service.py --project $PROJECT --model dtw --listen 5005 \\
    --serial-port $HAND_PORT --require-serial --quiet
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
# multi-user.target, NOT graphical.target: this must come up with no monitor,
# no keyboard, and nobody logged in.
WantedBy=multi-user.target
EOF

sudo cp "$TMP_UNIT" "$SERVICE"
rm -f "$TMP_UNIT"
sudo systemctl daemon-reload
sudo systemctl enable eeg-headset          # at every boot
ok "installed and enabled $SERVICE"

if [ "$NEEDS_REBOOT" = "1" ]; then
    say "7. Reboot required"
    cat <<'MSG'
   The UART and/or the dialout group only take effect after a reboot, so the
   service is enabled but NOT started yet -- starting it now would just fail on a
   port that does not exist.

       sudo reboot

   After the reboot it comes up on its own. Then check:
       journalctl -u eeg-headset -f
MSG
    exit 0
fi

sudo systemctl start eeg-headset
sleep 6
say "7. Result"
if systemctl is-active --quiet eeg-headset; then
    ok "eeg-headset is RUNNING and will start at every boot"
else
    warn "service is not active. Look at:  journalctl -u eeg-headset -n 40"
fi
journalctl -u eeg-headset -n 12 --no-pager | sed 's/^/   /'

cat <<EOF

   The Pi is done. It needs no screen from here on.

   Watch it:      journalctl -u eeg-headset -f
   Restart it:    sudo systemctl restart eeg-headset
   This Pi is at: $(hostname -I | awk '{print $1}')   (hostname: $(hostname))

   Now, on the LAPTOP:
       cd ~/neurograsp
       python3 dashboard.py --host $(hostname).local
   (if the name does not resolve, use the IP above)

EOF
