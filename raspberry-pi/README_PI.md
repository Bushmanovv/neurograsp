# This folder goes on the Raspberry Pi 5

Everything the Pi needs, and nothing else. The laptop keeps the dashboard; the Pi
keeps the model.

```
raspberry-pi/
├── install.sh                 <- run this on the Pi. It does everything.
├── pi_service.py              <- the service: model in RAM, UART open, listens on :5005
├── pi_receive.py              <- the wire format (pi_service imports it)
├── requirements-pi.txt        <- pinned to the versions the models were pickled with
└── EEG_GRADUATIO_PROJECT/     <- staged copy of the classifier (not in git, see below)
```

**Staging the classifier.** The repo keeps exactly one copy of the classifier, in
[`../eeg-classifier/`](../eeg-classifier/) — the Pi bundle used to carry a second,
byte-identical copy, which is 35 MB of duplicated model pickles. Stage it into this
folder before you ship, and `install.sh` finds it where it always did:

```bash
rsync -a --exclude DATA --exclude .venv --exclude __pycache__ \
    ../eeg-classifier/ EEG_GRADUATIO_PROJECT/
```

`DATA/` is the raw recordings; inference never opens them. The staged copy is
git-ignored, so it can't drift from the real one.

If you skip staging and run `install.sh` from a full checkout, it falls back to
`../eeg-classifier/` on its own — that works for a Pi that has the whole repo.

There is **no `.venv` here on purpose.** A virtualenv is not relocatable and the
laptop's is full of macOS binaries. `install.sh` builds a fresh Linux one on the Pi.

## What the Pi does

Boots with no screen, loads the model once, holds the UART to the hand open, sends
`rest` every 1.2 s so the hand's 3 s fail-safe never trips, and waits for the
laptop to send a 5 s `.edf` snippet on port 5005. Each snippet is classified in
~0.75 s and the confirmed command goes to the hand as a Contract A label.

## Steps (on the Pi)

**1. Get the folder onto the Pi.** From the laptop, one of:

```bash
# over the network
rsync -av ~/neurograsp/raspberry-pi/ pi@raspberrypi.local:~/eeg-pi/
# or copy it to a USB stick and drag it to /home/pi/eeg-pi
```

**2. Wire the hand to the Pi's UART.** Both sides are 3.3 V, so no level shifter —
but TX must meet RX, and the grounds must be common:

| Pi 5 | | ESP32 (hand) |
|---|---|---|
| GPIO 14 / TXD — header pin 8 | → | **RX** |
| GPIO 15 / RXD — header pin 10 | ← | **TX** |
| GND — header pin 6 | — | **GND** |

**On a Pi 5, `/dev/serial0` is NOT these pins.** The RP1 southbridge moved the
console UART to the dedicated 3-pin debug connector (`ttyAMA10`), and `serial0`
points at *that*. The hand on GPIO 14/15 is **`/dev/ttyAMA0`**, which only exists
once `dtparam=uart0=on` is in `/boot/firmware/config.txt`.

`install.sh` handles this: it adds the `dtparam` line (keeping a backup), puts you
in the `dialout` group, and pins the service to `/dev/ttyAMA0`.

**3. Install.**

```bash
cd ~/eeg-pi
chmod +x install.sh
./install.sh --check      # look first: changes nothing
./install.sh              # the real thing
```

It checks the machine, enables the UART, builds the venv, installs the pinned
dependencies, proves the model loads, then generates and enables the boot service.
If it changed the UART config or your groups it will tell you to reboot — the
service is enabled but deliberately not started, because the port does not exist
until you do.

Expect the dependency install to take a while — `tslearn` pulls in `numba` and
`llvmlite`.

**4. Confirm it survives a reboot, with no screen.**

```bash
sudo reboot
# wait ~40 s, then from the laptop:
#   cd ~/neurograsp/headset-link && python3 dashboard.py --host raspberrypi.local
```

The dashboard's *Link to the Pi* dot goes green on its own.

## The one line that matters

In `journalctl -u eeg-headset -f`, look for:

```
[serial] opened /dev/ttyAMA0 @ 115200 baud 8N1 (Contract A)
```

The service runs with `--require-serial`, so if that port will not open it **refuses
to start** and systemd shows the failure. That is deliberate. Without it, the
classifier would run perfectly, the dashboard would report `Hand commanded: C C C C`,
and the hand would not move — the labels going quietly into nothing. A dead service
is much easier to notice than a lying one.

If it does fail, the service's own error message lists the three things to check
(does the device exist, is `dtparam=uart0=on` set, are you in `dialout`).

## If something is wrong

| symptom | cause |
|---|---|
| `./install.sh` says "run it on the Pi" | you ran it on the laptop |
| `armv7l is not aarch64` | 32-bit OS; reflash with the 64-bit image |
| dashboard dot red, `Connection refused` | `journalctl -u eeg-headset -n 50` |
| dashboard dot red, name not resolving | use the IP: `hostname -I` on the Pi |
| `FileNotFoundError: models/...pkl` | the service is not running from the project dir (`WorkingDirectory`) |
| classifies fine, hand dead | serial — see "The one line that matters" |
| hand goes limp ~3 s after each command | you are running `pi_receive.py --cmd`, not `pi_service.py` |
