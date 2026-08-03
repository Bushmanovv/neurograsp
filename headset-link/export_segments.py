#!/usr/bin/env python3
"""Cut one replayable segment per gesture class and verify it fires its command.

For each of the five classes in ``config.LABEL_MAP`` this picks the busiest
``--seconds``-long window of a real recording (after ``CROP_SECONDS``), exports
it as raw int16 digital counts, and then *proves* it by pushing the exported
bytes through the exact path the Pi will run -- ``esp_headset.receiver`` on top
of ``inference.preprocess_stream``. A candidate that does not confirm its own
command, or that confirms someone else's, is rejected and the next one tried.

Output is a LittleFS image directory: ``seg<N>.bin`` + ``manifest.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from esp_headset import protocol
from esp_headset.protocol import Header
from esp_headset.receiver import Classifier

DEFAULT_PROJECT = Path.home() / "Desktop" / "EEG_GRADUATIO_PROJECT"
TOP_CANDIDATES = 6      # busiest windows to try per recording before moving on
FLASH_BUDGET = 1_500_000  # a 4 MB ESP32 with a no-OTA partition table


def _calibration(path: Path) -> tuple[float, float]:
    """Read (gain uV/LSB, offset uV) from the EDF header rather than assuming it.

    A symmetric physical range over the asymmetric int16 range gives a non-zero
    half-LSB offset; both constants are needed to recover the ADC's own codes.
    """
    import edfio

    edf = edfio.read_edf(path)
    cal = {((s.physical_max - s.physical_min) / (s.digital_max - s.digital_min),
            s.physical_min - (s.physical_max - s.physical_min)
            / (s.digital_max - s.digital_min) * s.digital_min)
           for s in edf.signals}
    if len(cal) != 1:
        raise ValueError(f"{path.name}: channels disagree on calibration: {sorted(cal)}")
    return cal.pop()


def _activity_profile(inference, cfg, data_uv: np.ndarray) -> np.ndarray:
    """Per-second activity (uV RMS) of each 2 s window, from CROP_SECONDS on."""
    sf, W = cfg.SFREQ, int(cfg.WINDOW_SEC * cfg.SFREQ)
    starts = range(cfg.CROP_SECONDS * sf, data_uv.shape[1] - W + 1, sf)
    return np.array([inference.window_activity(data_uv[:, s:s + W]) for s in starts])


def _candidate_starts(activity: np.ndarray, cfg, seconds: int) -> list[int]:
    """Sample offsets of the windows containing the most gate-passing seconds."""
    sf = cfg.SFREQ
    active = activity > cfg.ACTIVITY_THRESHOLD
    span = seconds - int(cfg.WINDOW_SEC)          # 1 s-hop windows fully inside
    if span <= 0 or len(active) < span:
        return []
    score = np.convolve(active.astype(int), np.ones(span, int), mode="valid")
    order = np.argsort(-score, kind="stable")[:TOP_CANDIDATES]
    return [(cfg.CROP_SECONDS + int(i)) * sf for i in order if score[i] > 0]


def _verify(clf: Classifier, counts: np.ndarray, header: Header, label: int):
    """Run the exported bytes through the receiver; return fires if they're all correct."""
    _, decoded = protocol.decode_segment(protocol.encode_segment(header, counts))
    fires = clf.fire(decoded, header)
    if not fires:
        return None, "no command confirmed"
    wrong = {f.name for f in fires if f.label != label}
    if wrong:
        return None, f"confirmed wrong command(s): {', '.join(sorted(wrong))}"
    return fires, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT,
                    help="EEG_GRADUATIO_PROJECT root")
    ap.add_argument("--seconds", type=int, default=5,
                    help="segment length (default 5: the predicted label still matches the "
                         "whole-recording path 100%%, and both the stream and the per-window "
                         "classification shrink with it. 30 maximises fidelity.)")
    ap.add_argument("--out", type=Path, default=Path("firmware/data"))
    ap.add_argument("--model", default="dtw")
    args = ap.parse_args(argv)

    project = args.project.resolve()
    if not (project / "inference.py").exists():
        print(f"error: no inference.py under {project}", file=sys.stderr)
        return 2

    clf = Classifier(project, model=args.model)   # also puts project on sys.path
    cfg, inference = clf.cfg, clf.inference
    import eeg_bci.loader as loader

    cwd = Path.cwd()
    import os
    os.chdir(project)                              # cfg.DATA_ROOT is relative
    try:
        recordings = loader.discover_recordings(cfg.DATA_ROOT)
    finally:
        os.chdir(cwd)

    by_class: dict[int, list] = {}
    for r in recordings:
        by_class.setdefault(r.label, []).append(r)
    # Prefer recordings not flagged noisy.
    for label in by_class:
        by_class[label].sort(key=lambda r: (r.noisy, str(r.path)))

    args.out.mkdir(parents=True, exist_ok=True)
    n_samples = args.seconds * cfg.SFREQ
    manifest, total = [], 0

    for label in sorted(by_class):
        class_name = cfg.LABEL_MAP[by_class[label][0].stem][1]
        char, action = cfg.COMMAND_MAP[label]
        print(f"\n=== label {label}: {class_name}  (command {char} - {action})")
        chosen = None

        for rec in by_class[label]:
            path = project / rec.path
            gain, offset = _calibration(path)
            raw = inference.load_edf(path)
            counts_full = protocol.volts_to_counts(raw.get_data(), gain, offset)
            data_uv, _ = inference.preprocess_stream(raw)   # mutates raw; counts taken first

            activity = _activity_profile(inference, cfg, data_uv)
            for s0 in _candidate_starts(activity, cfg, args.seconds):
                if s0 + n_samples > counts_full.shape[1]:
                    continue
                counts = np.ascontiguousarray(counts_full[:, s0:s0 + n_samples])
                header = Header(label, counts.shape[0], cfg.SFREQ, gain, offset, n_samples)
                fires, why = _verify(clf, counts, header, label)
                t0 = s0 / cfg.SFREQ
                if fires is None:
                    print(f"  [skip] {rec.path.name} t={t0:.0f}s: {why}")
                    continue
                print(f"  [ok]   {rec.path.name} t={t0:.0f}s: "
                      f"{len(fires)} x {char} (conf {fires[0].conf:.2f})")
                chosen = (rec, t0, counts, header, fires)
                break
            if chosen:
                break

        if chosen is None:
            print(f"error: no {args.seconds}s window of any {class_name} recording "
                  f"confirms command {char}. Nothing written.", file=sys.stderr)
            return 1

        rec, t0, counts, header, fires = chosen
        blob = protocol.encode_segment(header, counts)
        out = args.out / f"seg{label}.bin"
        out.write_bytes(blob)
        total += len(blob)
        clipped = int(np.sum(np.abs(counts) == 32767))
        manifest.append({
            "class_id": label, "class_name": class_name,
            "command_char": char, "action": action,
            "file": out.name, "bytes": len(blob),
            "source": str(rec.path), "t0_s": t0, "seconds": args.seconds,
            "sfreq": cfg.SFREQ, "n_ch": header.n_ch, "n_samples": n_samples,
            "scale_uv_per_lsb": header.scale_uv_per_lsb,
            "offset_uv": header.offset_uv,
            "clipped_samples": clipped,
            "verified_fires": [{"t": f.t, "char": f.char, "conf": round(f.conf, 3)}
                               for f in fires],
        })

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nwrote {len(manifest)} segments to {args.out}/  ({total:,} B, "
          f"{total/1024/1024:.2f} MiB)")
    if total > FLASH_BUDGET:
        print(f"WARNING: {total:,} B exceeds the ~{FLASH_BUDGET:,} B LittleFS budget "
              f"on a 4 MB no-OTA partition table.", file=sys.stderr)
    else:
        print(f"fits the ~{FLASH_BUDGET:,} B LittleFS budget "
              f"({100*total/FLASH_BUDGET:.0f}% used)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
