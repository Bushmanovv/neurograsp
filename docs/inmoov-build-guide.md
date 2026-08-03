# InMoov Right Hand + Forearm — Complete Project Guide

A full reference document for building an InMoov right hand with ESP32 Bluetooth control, custom phone app, and a 12V mains power system. Team build (3 people), based in Ramallah / Betunia.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [STL Files & Sources](#2-stl-files--sources)
3. [Complete Parts List (24 STLs)](#3-complete-parts-list-24-stls)
4. [Exploded Diagram Component Map](#4-exploded-diagram-component-map)
5. [Print Settings (3-Phase Plan)](#5-print-settings-3-phase-plan)
6. [Filament & Hardware](#6-filament--hardware)
7. [Servos & Motors](#7-servos--motors)
8. [Compatibility Check](#8-compatibility-check)
9. [Shopping Lists by Store](#9-shopping-lists-by-store)
10. [Electronics & Control System](#10-electronics--control-system)
11. [Power System (12V Setup)](#11-power-system-12v-setup)
12. [Master Connection Table](#12-master-connection-table)
13. [Build & Wiring Steps](#13-build--wiring-steps)
14. [Assembly Time Estimate](#14-assembly-time-estimate)
15. [Key Component Explanations](#15-key-component-explanations)
16. [Official Resources & Links](#16-official-resources--links)

---

## 1. Project Overview

**Goal:** Build an InMoov i2 right hand + classic forearm, controlled by an ESP32 over Bluetooth, with a custom phone app for user-customizable finger control and battery/stats monitoring.

**Architecture:**
```
Phone App (Bluetooth)
      ↕
    ESP32 (with expansion board)
      ↕ I2C
   PCA9685 (16ch PWM)
      ↕
  6× MG996R servos (5 fingers + 1 wrist)
```

**Generations bridged:** The build combines 3 InMoov design generations:
- **i2 Hand** (newest) — fingers, palm, covers
- **Classic Forearm** (robpart series) — forearm shell
- **RotaWrist + Servo Bed** — the bridge between hand and forearm

The **RotaWrist module is the physical adapter** between the new i2 hand and the classic forearm. The i2 hand bolts to RotaWrist3 on top (M8 bolt); RotaWrist1 glues to robpart2 at the bottom. The i2 hand and robpart shell never touch directly.

---

## 2. STL Files & Sources

| Source | What it provides | Link |
|--------|-----------------|------|
| InMoov i2 Hand | Hand parts (fingers, covers, wrist) | https://inmoov.fr/hand-i2/ |
| Classic Forearm | robpart2–5 shell | Thingiverse thing:17773 |
| Servo Bed | RobServoBed, cables, ring, tensioner | inmoov.fr Forearm-and-Servo-Bed gallery |
| Rotational Wrist | rotawrist1, 2, 3 | Thingiverse thing:25149 |

**Note:** The forearm shell parts (robpart2/3/4/5) were removed from the official servo-bed gallery section — they are reliably found on Thingiverse thing:17773.

---

## 3. Complete Parts List (24 STLs)

### Group A — Forearm Shell (robpart series)
| # | STL file | Description | Connects to |
|---|----------|-------------|-------------|
| 1 | robpart2V3.stl | Forearm wrist end cap | rotawrist1 (glued) |
| 2 | robpart3V3.stl | Forearm lower shell half | robpart4 |
| 3 | robpart4V3.stl | Forearm upper shell half | robpart3 + robpart5 |
| 4 | robpart5V3.stl | Forearm elbow end cap | robpart4 + servo bed |
| 5 | robcap3V1.stl | Forearm end cover cap | robpart5 (tip) |

### Group B — Rotational Wrist (RotaWrist series)
| # | STL file | Description | Connects to |
|---|----------|-------------|-------------|
| 6 | rotawrist1V3.stl | Wrist base — glues to robpart2 | robpart2 (glued) |
| 7 | rotawrist2.stl | Wrist gear housing (big gear) | rotawrist1 + rotawrist3 |
| 8 | rotawrist3V2.stl | Wrist top — mounts WristLarge | rotawrist2 + WristLarge |

### Group C — Servo Bed Internals
| # | STL file | Description | Connects to |
|---|----------|-------------|-------------|
| 9 | RobServoBedV6.stl | Main servo mounting plate (×5 servos) | robpart3/4/5 (screwed) |
| 10 | RobCableFrontV3.stl | Front cable guide bracket | servo bed front |
| 11 | RobCableBackV3.stl | Rear cable guide bracket | servo bed rear |
| 12 | RobRingV3.stl | Tendon retention ring | wrist area |
| 13 | TensionerRightV1.stl | Tendon tensioner (RIGHT hand) | servo bed side |
| 14 | servo-pulleyX5.stl | Servo horn pulleys ×5 | MG996R servo horns |

### Group D1 — i2 Hand Structural (no supports)
| # | STL file | Description | Connects to |
|---|----------|-------------|-------------|
| 15 | i2_WristLargeV2.stl | Main hand body / wrist base | rotawrist3 (M8 bolt) |
| 16 | i2_WristGearV1.stl | Tendon pass-through gear | WristLarge center |
| 17 | i2_FingersX5V2.stl | All 5 finger assemblies ×5 | WristLarge (M3×16mm) |
| 18 | i2_FingersMoldX5V3.stl | Silicone tip mold ×5 | casting tool only |
| 19 | i2_PulleyX5V1.stl | Hand-side tendon pulley ×5 | WristLarge pulley slot |
| 20 | i2_Adapter1109MG.stl | Servo adapter bracket | WristLarge side |

### Group D2 — i2 Hand Covers (supports required)
| # | STL file | Description | Connects to |
|---|----------|-------------|-------------|
| 21 | i2_CoverFingerV3.stl | Finger cover shell | fingers (snap fit) |
| 22 | i2_FingersTipX5V2.stl | Fingertip covers ×5 | finger tips (glued) |
| 23 | i2_HandCoverV1.stl | Top hand cover plate | WristLarge (M3 screw) |
| 24 | i2_PalmCoverV2.stl | Palm cover plate | WristLarge (M3 screw) |

---

## 4. Exploded Diagram Component Map

**Assembly axis (bottom → top):**
```
Group A (forearm shell)
   → Group B (rotawrist, inside A)
   → Group C (servo bed, inside A)
   → Group D1 (i2 hand structural, on top of B)
   → Group D2 (covers, outermost layer)
```

**Connection methods:**
- **glued** = permanent (epoxy)
- **M8 bolt** = wrist joint (WristLarge → RotaWrist3)
- **M3 screws** = covers
- **screwed** = servo bed

**Non-printed components** that sit inside Group C: MG996R ×6.

---

## 5. Print Settings (3-Phase Plan)

Print in 3 phases so assembly can start while later parts are still printing.

### Universal settings
- **Layer height:** 0.25mm (0.15mm for gears)
- **Infill:** 30% (50% for gears and pulleys)
- **Walls:** 2mm (3mm for gears)
- **Scale:** 100% — DO NOT RESCALE
- **First print:** CALIBRATOR.stl — test fit before printing real parts. If too tight, set horizontal expansion to −0.15mm.

### Phase 1 — Forearm + Wrist Backbone (print first)
| Part | Layer | Infill | Walls | Support | Raft |
|------|-------|--------|-------|---------|------|
| robpart2V3 | 0.25 | 30% | 2mm | NO | YES (anti-warp) |
| robpart3V3 | 0.25 | 30% | 2mm | NO | YES |
| robpart4V3 | 0.25 | 30% | 2mm | NO | YES |
| robpart5V3 | 0.25 | 30% | 2mm | NO | YES (~7hr print) |
| robcap3V1 | 0.25 | 30% | 2mm | NO | NO |
| rotawrist1V3 | 0.25 | 30% | 3mm | YES | NO |
| rotawrist2 | 0.15 | 50% | 3mm | NO | NO |
| rotawrist3V2 | 0.25 | 30% | 3mm | NO | NO |
| RobServoBedV6 | 0.2 | 30% | 2mm | NO | NO |
| RobCableFrontV3 | 0.2 | 30% | 2mm | NO | NO |
| RobCableBackV3 | 0.2 | 30% | 2mm | NO | NO |

### Phase 2 — Hand Core (print while assembling Phase 1)
| Part | Layer | Infill | Walls | Support | Raft |
|------|-------|--------|-------|---------|------|
| i2_FingersX5V2 | 0.25 | 30% | 2mm | NO | NO |
| i2_FingersMoldX5V3 | 0.25 | 30% | 2mm | NO | NO |
| i2_WristLargeV2 | 0.25 | 30% | 2mm | NO | NO |
| i2_WristGearV1 | 0.15 | 50% | 3mm | NO | NO |
| i2_PulleyX5V1 | 0.15 | 50% | 3mm | NO | NO |
| RobRingV3 | 0.2 | 30% | 2mm | NO | NO |
| TensionerRightV1 | 0.2 | 30% | 2mm | NO | NO |
| servo-pulleyX5 | 0.15 | 50% | 3mm | NO | NO |

### Phase 3 — Covers + Tips (print last)
| Part | Layer | Infill | Walls | Support | Raft |
|------|-------|--------|-------|---------|------|
| i2_CoverFingerV3 | 0.25 | 30% | 2mm | YES | If needed |
| i2_FingersTipX5V2 | 0.25 | 30% | 2mm | YES | If needed |
| i2_HandCoverV1 | 0.25 | 30% | 2mm | YES | If needed |
| i2_PalmCoverV2 | 0.25 | 30% | 2mm | YES | If needed |
| i2_Adapter1109MG | 0.25 | 30% | 2mm | YES | If needed |

### Redrill operations (mandatory after printing)
- **3mm bit** → all finger hinge holes
- **6mm bit** → robpart2 side holes
- **8mm bit** → rotawrist3 + WristLarge
- **2.5mm bit** → rotawrist2
- **2mm bit** → servo-pulleyX5

---

## 6. Filament & Hardware

### Filament
- **Material:** PLA+ recommended (PLA or PETG acceptable; ABS only with enclosure)
- **Color:** WHITE (official InMoov standard)
- **Diameter:** 1.75mm, 0.4mm nozzle
- **Total needed:** ~850g (buy 2× 1kg spools for safety margin)
- **Temps:** Bed 60°C (PLA), Nozzle 200–210°C (PLA)

### Key hardware specs
- **M8 bolt:** M8 × 80mm (or print the STL — recommended for the wrist since it's not load-bearing)
- **Fishing line:** Braided 0.8mm, 200LB — 5 lengths
- **PTFE tube:** ID 1.5mm × OD 2.5mm — buy **2 meters**
  - One **separate tube per finger** (5 tubes total)
  - Cut lengths: Thumb 335mm, Index 300mm, Middle 300mm, Ring 300mm, Pinky 360mm
- **Springs:** Extension springs 0.5mm × 1cm (×5)
- **Mini clamp / C-ring:** locks the M8 printed bolt groove at the wrist joint (prevents hand detaching)

### Glue usage
| Glue | Use for |
|------|---------|
| **Epoxy (2-component)** | rotawrist1→robpart2, robpart shell joints (structural, permanent) |
| **Super glue (CA)** | Fishing line knots, fingertip covers, small fixes |

> ⚠️ Never use super glue for rotawrist1→robpart2 — it's brittle and cracks under wrist rotation. Epoxy only.

---

## 7. Servos & Motors

**Final choice: 6× MG996R** (all same model for consistency).

| Position | Servo | Channel | Start angle |
|----------|-------|---------|-------------|
| Thumb | MG996R | CH0 | 150° |
| Index | MG996R | CH1 | 150° |
| Middle | MG996R | CH2 | 150° |
| Ring | MG996R | CH3 | 150° |
| Pinky | MG996R | CH4 | 150° |
| Wrist | MG996R | CH5 | 90° (center) |

**Servo notes:**
- MG996R voltage range: 4.8V–7.2V (do NOT exceed)
- "Burns easily" = electrical overheating/burnout, not literal fire. Avoid sustained stall load.
- Original recommended finger servo was HK15298B (unavailable locally). MG996R works fine.
- Set each servo to its start angle BEFORE physically mounting.
- MG995 and MG996R are physically identical (40.5×19.7×42.5mm) and interchangeable.

---

## 8. Compatibility Check

All 7 cross-generation checks PASSED — no incompatibilities.

| Check | Result |
|-------|--------|
| WristLarge → RotaWrist3 | ✅ M8 bolt + mini clamp |
| RotaWrist → forearm | ✅ via rotawrist1→robpart2 (dry-fit V2 vs V3 glue face) |
| ServoBedV6 in forearm | ✅ spans robpart3/4/5 (verify screw bosses by dry-fit) |
| Two pulleys (i2_PulleyX5V1 vs servo-pulleyX5) | ✅ Different parts, both needed |
| Tensioner → ServoBed | ✅ Same generation, correct hand |
| RobRing ↔ rotawrist2 | ✅ Same generation |
| i2_WristGear ↔ RotaWrist | ✅ Different mechanisms, coexist |

**Two dry-fit checks before gluing:** (1) robpart2 V2→V3 glue face, (2) servo-bed screw bosses in shell.

---

## 9. Shopping Lists by Store

### Abu Ein — Betunia (mechanical, ~₪122)
Screws (M3/M4/M8), wood screws, mini clamp, epoxy, super glue, gear grease, black spray paint, braided fishing line, extension springs, rubber tube pieces.

### Labco — Ramallah (electronics, ~₪736 originally)
ESP32, Arduino (later dropped), buck/boost converter, capacitors, resistors, PCB, pin headers, terminal blocks, battery, charger, XT60, wires, servo cables, ribbon cable, PTFE tube, filament.

### Robotics Store — Ramallah
MG996R servos, PCA9685, multimeter (already purchased some).

### Extra parts for final 12V setup (~₪81, all Labco)
| Item | Qty | Price |
|------|-----|-------|
| XL4015 5A buck converter (LED display) | ×1 | ₪35 |
| DC pigtail MALE 5.5×2.1mm center-positive | ×2 | ₪10 |
| 470µF capacitor (16V+) | ×2 | ₪6 |
| Jumper wires female-female | ×1 pack | ₪15 |
| Silicone wire 20AWG red + black | ×2m | ₪15 |

---

## 10. Electronics & Control System

### Components (final)
- **ESP32 WROOM** + Goouuu 38P/V4 expansion board (DC jack rated 6.5–16V)
- **PCA9685** 16-channel PWM driver
- **6× MG996R** servos
- **12V AC-DC SMPS** (metal enclosed power supply)
- **XL4015** buck converter (12V → 6V)

### Why ESP32 over Arduino
- 16 hardware PWM channels, built-in Bluetooth + WiFi
- Higher PWM resolution (16-bit)
- Needs ESP32Servo library (no native servo lib)
- Set MIN_PULSE=500, MAX_PULSE=2500 to fix the 90°-instead-of-180° issue
- Add capacitor on power rail to prevent brownout resets

### Planned phone app features
- Per-finger control (speed, range, min/max angle)
- Custom gestures (fist, open, point, peace) + saved sequences
- Live battery/voltage reading (if monitor circuit used)
- Emergency stop

---

## 11. Power System (12V Setup)

**The 12V supply splits two ways:**
```
220V mains → 12V SMPS box
                  ├──→ ESP32 expansion DC jack (12V direct — board rated 6.5–16V) ✅
                  └──→ XL4015 buck → 6V → PCA9685 V+ → 6 servos ✅
```

**Critical rules:**
1. **12V NEVER touches the servos or PCA9685 V+** — it would instantly burn them.
2. **Set XL4015 to 6.0V** (use its LED display) BEFORE connecting the PCA9685 or servos.
3. The ESP32 board's onboard regulator drops 12V → 5V internally for the ESP32 chip.

**Connecting 12V to the ESP32 board:** Use a **DC pigtail (MALE, 5.5×2.1mm, center-positive)**. Screw the red/black bare wires to the supply's +V/−V, plug the barrel into the board's DC jack. Multimeter-check polarity (center = +) before plugging in.

**Pi 5 note:** If a Raspberry Pi 5 is added later for model computation, power it SEPARATELY with the official 27W USB-C PSU. Never share the servo power rail. Connect the grounds together (common ground) but keep power separate.

---

## 12. Master Connection Table

### Group 1 — AC Mains (⚠️ check twice)
| Wire | From | To | Color |
|------|------|-----|-------|
| 1 | Wall Live | SMPS L | Brown |
| 2 | Wall Neutral | SMPS N | Blue |
| 3 | Wall Earth | SMPS ⏚ | Green/yellow |

### Group 2 — 12V Output (splits two ways)
| Wire | From | To | Color |
|------|------|-----|-------|
| 4 | SMPS +V | XL4015 IN+ | Red |
| 5 | SMPS −V | XL4015 IN− | Black |
| 6 | SMPS +V | DC pigtail red wire | Red |
| 7 | SMPS −V | DC pigtail black wire | Black |
| 8 | DC pigtail barrel | ESP32 board DC jack | 12V plug |

### Group 3 — XL4015 Output (set to 6V FIRST)
| Wire | From | To | Color |
|------|------|-----|-------|
| 9 | XL4015 OUT+ | PCA9685 V+ | Red |
| 10 | XL4015 OUT− | PCA9685 GND | Black |
| 11 | 470µF cap + (long leg) | PCA9685 V+ rail | — |
| 12 | 470µF cap − (short leg) | PCA9685 GND rail | — |

### Group 4 — ESP32 ↔ PCA9685 (I2C + logic)
| Wire | ESP32 board pin | PCA9685 pin | Color |
|------|-----------------|-------------|-------|
| 13 | P21 (GPIO21) | SDA | Blue |
| 14 | P22 (GPIO22) | SCL | Yellow |
| 15 | 5V pin | VCC | Red |
| 16 | GND pin | GND | Black |

### Group 5 — Servos (plug directly)
| Servo | Channel | Orientation |
|-------|---------|-------------|
| Thumb | CH0 | brown→GND, red→V+, orange→signal |
| Index | CH1 | same |
| Middle | CH2 | same |
| Ring | CH3 | same |
| Pinky | CH4 | same |
| Wrist | CH5 | same |

---

## 13. Build & Wiring Steps

### Mechanical assembly (6 sessions, ~25–30 hrs across 3 people)

**Session 1 — Forearm + RotaWrist (~5hrs)**
1. Redrill ALL parts
2. Dry-fit rotawrist1 on robpart2 (check orientation!)
3. Glue rotawrist1 to robpart2 (epoxy)
4. Glue robpart3 + robpart4
5. Assemble rotawrist2 + rotawrist3 with gear grease

**Session 2 — Servo bed (~4hrs)**
1. Set all 6 servos to start position FIRST
2. Mount 5 finger servos in RobServoBedV6
3. Press servo-pulleyX5 onto each horn
4. Dry-fit servo bed into shell
5. Mount wrist servo in rotawrist2

**Session 3 — Fingers (~5hrs, most patience)**
1. Cut PTFE tubes to lengths
2. Assemble finger sections (Middle→Index→Ring→Pinky→Thumb)
3. Run fishing line through each finger (30cm), knot + super glue
4. Thread PTFE tubes through WristGear

**Session 4 — Hand assembly (~4hrs)**
1. Mount WristLarge to rotawrist3 (M8 bolt + mini clamp)
2. Mount fingers to WristLarge (M3×16mm)
3. Connect fishing lines through PTFE to servo pulleys
4. Dry-test finger movement by hand

**Session 5 — Electronics (~4hrs)** — see wiring phases below

**Session 6 — Covers + final (~3hrs)**
1. Tap M3 holes
2. Route ribbon cable into PalmCover grooves (don't pinch!)
3. Mount HandCover + PalmCover
4. Glue FingerTips
5. Final tensioning + testing

### Electrical wiring phases (strict order)
- **Phase A** — Wire AC mains to SMPS (wires 1–3). Confirm 12V output.
- **Phase B** — Wire SMPS to XL4015 IN only (wires 4–5). Set LED to exactly 6.0V. Power off. ⚠️ **Gate: nothing downstream until 6.0V confirmed.**
- **Phase C** — Wire DC pigtail (wires 6–8). Multimeter-check barrel polarity. Plug into ESP32.
- **Phase D** — Wire XL4015 OUT to PCA9685 V+/GND (wires 9–10). Solder capacitor (11–12).
- **Phase E** — Wire 4 I2C jumpers (wires 13–16).
- **Phase F** — Power on. Upload I2C scanner. Confirm PCA9685 at 0x40. Power off.
- **Phase G** — Plug all 6 servos into CH0–CH5. Upload servo test. Test each one by one.

---

## 14. Assembly Time Estimate

| Builder type | Total time |
|-------------|------------|
| Experienced maker | 20–25 hours |
| First-time team of 3 | 30–40 hours (spread over 5–6 sessions / 2–3 weekends) |

**Longest/hardest steps:** finger fishing-line routing (Session 3) and electronics debugging (Session 5).

---

## 15. Key Component Explanations

**PTFE tube** — Acts like a Bowden cable sheath. The fishing line (tendon) slides through it with near-zero friction from servo to fingertip. Without it, the line would erode grooves into the printed plastic and snap. One separate tube per finger (5 total).

**Mini clamp / C-ring** — A retaining clip that sits in the groove of the printed M8 bolt at the WristLarge→RotaWrist3 joint. Stops the bolt from backing out under rotation (which would detach the hand from the wrist).

**i2_WristGearV1 vs rotawrist2** — Different mechanisms that coexist:
- rotawrist2 = the big gear that ROTATES the whole wrist (driven by MG996R)
- i2_WristGearV1 = the tendon pass-through gear; PTFE tubes run through its Teflon-pipe holes. Does NOT drive rotation.

**Two pulleys (both required):**
- servo-pulleyX5 = mounts on servo horns inside the bed, winds the tendon line
- i2_PulleyX5V1 = hand-side, redirects the tendon at the hand

**XL4015 buck converter** — Steps 12V DOWN to 6V for the servos. Has an LED display so you can see and set the voltage precisely. (Opposite of a boost converter, which steps voltage UP.)

**470µF capacitor** — Sits across the 6V servo rail near the PCA9685. Absorbs the current spike when all servos move at once, preventing the ESP32 from brownout-resetting. Long leg = +, short leg = −.

---

## 16. Official Resources & Links

### STL downloads
- i2 Hand: https://inmoov.fr/hand-i2/
- Classic forearm: Thingiverse thing:17773
- Rotational wrist: Thingiverse thing:25149

### Assembly guides
- Hand + Forearm: https://inmoov.fr/hand-and-forarm/
- Hand + Forearm 3D views: https://inmoov.fr/build-yours/hand-and-forarm-assembly-3d-views/
- Rotational wrist: https://inmoov.fr/rotational-wrist/
- Finger starter: https://inmoov.fr/finger-starter/
- Lining & tightening tendons: https://inmoov.fr/lining-and-tighting-the-tendons/

### Videos
- Full hand + forearm build: https://www.youtube.com/watch?v=4t1daCFQ1OE
- Tendon knot on servo pulley: https://www.youtube.com/watch?v=n_QEnOGz0us
- RotaWrist assembly (Civrays): https://www.youtube.com/watch?v=9KJu98NeDBg

---

*Document compiled for the InMoov right hand team build. Verify all redrill/tap operations on a test print before committing. Always set the buck converter to the correct voltage before connecting servos.*
