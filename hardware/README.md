# hardware

The physical hand: what to print, in what order, and what to buy.

**24 prints · 3 phases · ~62 h of printer time.** PLA or ABS, 0.4 mm nozzle,
**100% scale — do not rescale.**

## Start here

**[`3d-print/InMoov_RightHand_Forearm_PRINT_READY/BUILD_CHECKLIST.md`](3d-print/InMoov_RightHand_Forearm_PRINT_READY/BUILD_CHECKLIST.md)**
is the real document — every part with its layer height, infill, wall thickness,
supports, raft and time estimate, arranged so assembly of one phase happens while
the next phase prints.

The phases are ordered by what unblocks the build, not by what's convenient to
slice:

| Phase | What | Prints | Time |
|---|---|---|---|
| 1 | Forearm shell, rotational wrist, servo bed | 10 | ~33 h |
| 2 | i2 hand core — print while assembling phase 1 | 8 | ~18.5 h |
| 3 | Covers and fingertips — needed only at final assembly | 6 | ~10.5 h |

Two things in there are easy to skip and expensive to skip: **redrill every
finger hinge with a 3 mm bit** and `i2_WristLargeV2` with an **M8** bit after
printing, and **dry-fit before gluing** — `robpart2V3` + `rotawrist1V3` is a
permanent joint.

## What's in each folder

| | |
|---|---|
| `3d-print/InMoov_RightHand_Forearm_PRINT_READY/` | The curated build — exactly the 24 STLs used, plus the checklist. **Print from here.** |
| `3d-print/Inmoov-hand-i2/` | Upstream i2 hand revision, left and right. Provenance for the hand parts. |
| `3d-print/thingiverse-17773-inmoov-hand/` | The Thingiverse derivative, with its own `LICENSE.txt`. |
| `3d-print/*.stl` (loose) | Forearm, wrist and servo-bed parts sitting at top level for convenience. |
| `3d-print/*.zip` | The original downloads, unmodified. Redundant with the extracted folders — kept as provenance. |
| `bom/inmoov-shopping-list.html` | Parts and sourcing: servos, bearings, fasteners, tendon line, filament. Open it in a browser. |

## Non-printed parts

6 servos (5 fingers + 1 wrist rotation), M3 screws for the covers, an M8 bolt for
the wrist joint, and braided tendon line. The servo bed takes the five finger
servos inside the forearm and drives the fingers through `servo-pulleyX5` horns.

Wiring, power distribution, and which GPIO drives which finger are in
[`../hand-firmware/include/config.h`](../hand-firmware/include/config.h) and
[`../docs/diagrams/`](../docs/diagrams/). Before running a built-in gesture on a
freshly assembled hand, measure each servo's real travel with
[`../hand-firmware/tools/calibrate_servos.py`](../hand-firmware/tools/calibrate_servos.py) —
the shipped limits are deliberately wide, and a stalled hobby servo will strip
its own gears inside a closed forearm without making a sound.

## Credit and licence

The hand and forearm geometry is **Gaël Langevin's InMoov** (<https://inmoov.fr/>),
licensed **CC BY-NC 3.0**. It is redistributed here unmodified under those terms.
This project printed, assembled, tendoned and drove it — it did not design it.
Commercial use requires permission from the original author. See
[`../LICENSE`](../LICENSE).
