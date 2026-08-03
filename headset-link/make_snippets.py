#!/usr/bin/env python3
"""Cut one real .edf snippet per command and prove the Pi's own CLI accepts it.

The ESP32 stores these five files and sends one, byte for byte, over Bluetooth.
The Pi writes the bytes to disk and runs its existing pipeline -- nothing on the
Pi changes, because the payload is just an EDF.

Reuses the windows already verified in firmware/data/manifest.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_PROJECT = Path.home() / "Desktop" / "EEG_GRADUATIO_PROJECT"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    ap.add_argument("--manifest", type=Path, default=Path("firmware/data/manifest.json"))
    ap.add_argument("--out", type=Path, default=Path("firmware/esp32_headset/data"))
    args = ap.parse_args(argv)

    project = args.project.resolve()
    sys.path.insert(0, str(project))
    import mne
    from inference import load_edf
    import eeg_bci.config as cfg

    mne.set_log_level("ERROR")
    man = sorted(json.loads(args.manifest.read_text()), key=lambda e: e["class_id"])
    args.out.mkdir(parents=True, exist_ok=True)

    out_manifest = []
    for e in man:
        raw = load_edf(project / e["source"])          # reorders to config.ALL_CH
        t0 = e["t0_s"]
        raw.crop(tmin=t0, tmax=t0 + e["seconds"] - 1.0 / cfg.SFREQ)

        dst = args.out / f"s{e['class_id']}.edf"
        tmp = dst.with_suffix(".tmp.edf")
        mne.export.export_raw(tmp, raw, fmt="edf", overwrite=True, verbose="ERROR")
        tmp.replace(dst)

        # Read it back through the Pi's own loader.
        back = load_edf(dst)
        assert back.ch_names == list(cfg.ALL_CH), back.ch_names
        assert back.info["sfreq"] == cfg.SFREQ, back.info["sfreq"]

        size = dst.stat().st_size
        out_manifest.append({
            "class_id": e["class_id"], "class_name": e["class_name"],
            "command_char": e["command_char"], "action": e["action"],
            "file": dst.name, "bytes": size, "seconds": e["seconds"],
            "source": e["source"], "t0_s": t0,
        })
        print(f"  s{e['class_id']}.edf  {e['class_name']:<15} -> {e['command_char']}  "
              f"{size:>7,} B   {back.n_times/cfg.SFREQ:.1f}s  {len(back.ch_names)}ch  OK")

    (args.out / "snippets.json").write_text(json.dumps(out_manifest, indent=2) + "\n")
    total = sum(m["bytes"] for m in out_manifest)
    print(f"\n5 snippets = {total:,} B ({total/1024:.0f} KiB) -> fits LittleFS trivially")
    return 0


if __name__ == "__main__":
    sys.exit(main())
