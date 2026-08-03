# InMoov Right Hand + Forearm — Phased Print Checklist

**Build:** InMoov right hand (i2) + classic forearm shell + servo bed + rotational wrist
**Total prints:** 24 (23 robot parts + 1 casting mold) · **3 print phases** · **~62 h total**
**Generated:** 2026-06-10

> Settings are InMoov-community baselines. Material **PLA or ABS**, nozzle **0.4 mm**.
> All parts print at **100 % scale — do NOT rescale.** "Supp." = support material,
> "Raft" = bed-adhesion raft. Tune to your printer/filament. Time estimates assume
> ~50–60 mm/s; faster/slower printers will differ.

---

## ⚠️ Read before printing

1. **Print a calibration cube/part first.** Test-fit, then set **horizontal expansion to −0.15 mm** if parts come out too tight.
2. **Print in the 3 phases below.** Phase 1 (forearm + wrist backbone) → Phase 2 (hand core, print *while* assembling Phase 1) → Phase 3 (covers & tips, print *while* doing Phase 2 assembly).
3. **Dry-fit before gluing:** after `robpart2V3` + `rotawrist1V3` check the glue-face alignment; after `RobServoBedV6` test it inside the `robpart3/4/5` shell before final assembly.
4. **Post-print drilling:** redrill ALL finger hinge holes with a **3 mm** bit, and redrill `i2_WristLargeV2` with an **M8** bit.

---

## PHASE 1 — FOREARM & WRIST BACKBONE  ·  *Print first*

> *"Start assembling the forearm as soon as this phase is done."*

| Done | STL file | Layer | Infill | Walls | Supp. | Raft | ~Time |
|:--:|----------|:--:|:--:|:--:|:--:|:--:|:--:|
| ☐ | `robpart2V3.stl` | 0.25 mm | 30% | 2 mm | No | **Yes** | ~5 h |
| ☐ | `robpart3V3.stl` | 0.25 mm | 30% | 2 mm | No | **Yes** | ~5 h |
| ☐ | `robpart4V3.stl` | 0.25 mm | 30% | 2 mm | No | **Yes** | ~5 h |
| ☐ | `robpart5V3.stl` | 0.25 mm | 30% | 2 mm | No | **Yes** | ~7 h |
| ☐ | `rotawrist1V3.stl` | 0.25 mm | 30% | 3 mm | **Yes**\* | No | ~2 h |
| ☐ | `rotawrist2.stl` | **0.15 mm** | 30% | 3 mm | No | No | ~2.5 h |
| ☐ | `rotawrist3V2.stl` | 0.25 mm | 30% | 3 mm | No | No | ~1.5 h |
| ☐ | `RobServoBedV6.stl` | 0.2 mm | 30% | 2 mm | No | No | ~3.5 h |
| ☐ | `RobCableFrontV3.stl` | 0.2 mm | 30% | 2 mm | No | No | ~1 h |
| ☐ | `RobCableBackV3.stl` | 0.2 mm | 30% | 2 mm | No | No | ~0.5 h |

**Phase 1: 10 prints · ~33 h total**

- ⚠️ **Print `robpart2V3` + `rotawrist1V3` first** — they glue together and the builder needs them before anything else.
- ⚠️ `robpart5V3` is the longest print (~7 h).
- ⚠️ `rotawrist2`: spray-paint **black** after printing (grease stains show on light filament); 0.15 mm layer = best gear quality.
- \* `rotawrist1V3` supports: remove after printing. Shell rafts are anti-warp insurance.

> ### ▶ ASSEMBLY UNLOCKED
> Glue `rotawrist1V3` to `robpart2V3` (dry-fit first), build the rotational-wrist gear stack (`rotawrist2` → `rotawrist3V2`), join the forearm shells `robpart2 → 5`, and seat `RobServoBedV6` with its front/back cable guides inside the shell. **The forearm + wrist backbone now stands and is ready to receive the hand.**

---

## PHASE 2 — HAND CORE  ·  *Print while assembling Phase 1*

> *"Start assembling fingers and wrist while Phase 1 is being built."*

| Done | STL file | Layer | Infill | Walls | Supp. | Raft | ~Time |
|:--:|----------|:--:|:--:|:--:|:--:|:--:|:--:|
| ☐ | `i2_WristLargeV2.stl` | 0.25 mm | 30% | 2 mm | No | No | ~3.5 h |
| ☐ | `i2_WristGearV1.stl` | **0.15 mm** | 50% | 3 mm | No | No | ~3.5 h |
| ☐ | `i2_FingersX5V2.stl` | 0.25 mm | 30% | 2 mm | No | No | ~4.5 h |
| ☐ | `i2_FingersMoldX5V3.stl` | 0.25 mm | 30% | 2 mm | No | No | ~2 h |
| ☐ | `RobRingV3.stl` | 0.2 mm | 30% | 2 mm | No | No | ~1 h |
| ☐ | `TensionerRightV1.stl` | 0.2 mm | 30% | 2 mm | No | No | ~1 h |
| ☐ | `servo-pulleyX5.stl` | **0.15 mm** | 50% | 3 mm | No | No | ~1.5 h |
| ☐ | `robcap3V1.stl` | 0.25 mm | 30% | 2 mm | No | No | ~1.5 h |

**Phase 2: 8 prints · ~18.5 h total**

- ⚠️ `TensionerRightV1` is the **RIGHT**-hand version — do NOT substitute a Left.
- ⚠️ `servo-pulleyX5`: high infill (50%) — it takes direct servo load.
- `i2_WristGearV1` & `servo-pulleyX5` at 0.15 mm = best quality (gears/pulleys).
- Redrill `i2_WristLargeV2` with an **M8** bit after printing.
- `i2_FingersMoldX5V3` is a casting jig — printed, but **not** one of the 23 structural robot parts.

> ### ▶ ASSEMBLY UNLOCKED
> Mount `i2_WristGearV1` + `i2_WristLargeV2` (redrilled M8) and bolt WristLarge to RotaWrist3; install the fingers (`i2_FingersX5V2`); fit `servo-pulleyX5` onto the finger-servo horns, add `RobRingV3` + the right-hand `TensionerRightV1`, and cap the forearm end with `robcap3V1`. **The hand now grips and the wrist rotates — you have a functional hand + forearm.**

---

## PHASE 3 — COVERS & TIPS  ·  *Print last (needed only at final assembly)*

> *"The hand works without these — print them while doing Phase 2 assembly."*

| Done | STL file | Layer | Infill | Walls | Supp. | Raft | ~Time |
|:--:|----------|:--:|:--:|:--:|:--:|:--:|:--:|
| ☐ | `i2_CoverFingerV3.stl` | 0.25 mm | 30% | 2 mm | **Yes** | if req. | ~2 h |
| ☐ | `i2_FingersTipX5V2.stl` | 0.25 mm | 30% | 2 mm | **Yes** | if req. | ~1.5 h |
| ☐ | `i2_HandCoverV1.stl` | 0.25 mm | 30% | 2 mm | **Yes** | if req. | ~2.5 h |
| ☐ | `i2_PalmCoverV2.stl` | 0.25 mm | 30% | 2 mm | **Yes** | if req. | ~2.5 h |
| ☐ | `i2_PulleyX5V1.stl` | 0.25 mm | 30% | 2 mm | No | No | ~1.5 h |
| ☐ | `i2_Adapter1109MG.stl` | 0.25 mm | 30% | 2 mm | **Yes** | if req. | ~0.5 h |

**Phase 3: 6 prints · ~10.5 h total**

- ⚠️ `i2_CoverFingerV3`: print **standing up** for the best result.
- ⚠️ `i2_PalmCoverV2`: route the ribbon-cable grooves carefully during assembly.
- Covers need supports; use a raft only "if req." (i.e. only if the part lifts off the bed).

> ### ▶ ASSEMBLY UNLOCKED
> Snap on the fingertips (`i2_FingersTipX5V2`), fit the finger / hand / palm covers, add the hand-side `i2_PulleyX5V1` and the `i2_Adapter1109MG` servo adapter. **The build is now fully dressed and visually complete — done.**

---

## Build totals & sign-off

| | |
|---|---|
| **Total robot parts** | **23** † |
| **Total prints to make** | **24** — Phase 1: 10 · Phase 2: 8 · Phase 3: 6 |
| **Est. total print time** | ~62 h (P1 ~33 h · P2 ~18.5 h · P3 ~10.5 h) — varies by printer |
| **Print order** | 3 phases, see above |

† `i2_FingersMoldX5V3` is a mold/jig for casting flexible finger joints — it is printed but is not a structural robot part, so it is not counted in the 23.

```
Printer / operator: ______________________________

Date started:       ______________________________

Date completed:     ______________________________
```

---

## Reference — file sources & purpose

| STL file | Source archive | Purpose |
|----------|----------------|---------|
| i2_FingersX5V2 | `Inmoov-hand-i2.zip → i2_RightHand/` | 5 finger assemblies (3 phalanges each) — core moving fingers |
| i2_FingersTipX5V2 | `Inmoov-hand-i2.zip` | 5 fingertip caps (snap onto finger ends) |
| i2_FingersMoldX5V3 | `Inmoov-hand-i2.zip` | Mold for casting flexible finger joints (jig, not a robot part) |
| i2_CoverFingerV3 | `Inmoov-hand-i2.zip` | Finger cover plate over palm tendon routing |
| i2_PalmCoverV2 | `Inmoov-hand-i2.zip` | Palm cover / front shell of the hand |
| i2_HandCoverV1 | `Inmoov-hand-i2.zip` | Back hand cover shell |
| i2_PulleyX5V1 | `Inmoov-hand-i2.zip` | 5 hand-side tendon pulleys (route finger lines through wrist) |
| i2_WristGearV1 | `Inmoov-hand-i2.zip` | Wrist tendon pass-through gear (hand side) |
| i2_WristLargeV2 | `Inmoov-hand-i2.zip` | Large wrist coupling joining hand to forearm |
| i2_Adapter1109MG | `Inmoov-hand-i2.zip` | Servo adapter for MG-class servo horn |
| robpart2V3 | `Hand robot InMoov - 17773 (1).zip → files/` | Forearm shell segment 2 |
| robpart3V3 | `Hand robot InMoov - 17773 (1).zip` | Forearm shell segment 3 |
| robpart4V3 | `Hand robot InMoov - 17773 (1).zip` | Forearm shell segment 4 |
| robpart5V3 | `Hand robot InMoov - 17773 (1).zip` | Forearm shell segment 5 |
| robcap3V1 | `Hand robot InMoov - 17773 (1).zip` | Forearm end cap |
| RobServoBedV6 | `hardware/3d-print/` (servo bed) | Main servo bed — holds the 5 finger servos inside the forearm |
| RobCableFrontV3 | `hardware/3d-print/` | Front cable guide / tendon routing plate |
| RobCableBackV3 | `hardware/3d-print/` | Back cable guide / tendon routing plate |
| RobRingV3 | `hardware/3d-print/` | Retaining ring at the wrist end of the servo bed |
| TensionerRightV1 | `hardware/3d-print/` | Right-hand tendon tensioner block |
| servo-pulleyX5 | `hardware/3d-print/` | 5 servo-horn pulleys — wind the tendon lines on each servo |
| rotawrist1V3 | `hardware/3d-print/` (RotaWrist) | Rotational wrist part 1 (drive/mount → glues to robpart2) |
| rotawrist2 | `hardware/3d-print/` | Rotational wrist part 2 (rotating coupler / big gear) |
| rotawrist3V2 | `hardware/3d-print/` | Rotational wrist part 3 (bolts to i2_WristLargeV2) |

**How the generations bridge:** the i2 hand never touches the classic forearm directly — the **RotaWrist module is the adapter**. `i2_WristLargeV2 → rotawrist3V2` joins with an **M8 printed bolt**; `rotawrist1V3 → robpart2V3` is **glued**. "X5" parts (FingersX5, FingersTipX5, PulleyX5, servo-pulleyX5) are sets of 5 — confirm all 5 are on the plate or duplicate ×5 in your slicer.

**Sources:** inmoov.fr/hand-i2, inmoov.fr/rotational-wrist, Thingiverse 25149 (Rotation Wrist, Gael Langevin), Thingiverse 6653167 (RobCableFront + i2_WristGear, moz4r).
