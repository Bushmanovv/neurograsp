# prep_fs.py — PlatformIO extra_script (pre:).
#
# Builds the LittleFS image from a STAGED copy of data/ instead of data/ itself:
#   * text assets (.html .css .js .gltf .svg) are gzipped — ESPAsyncWebServer
#     serves `file.gz` transparently when `file` is requested, so the 600 KB
#     Three.js becomes ~150 KB on flash and loads much faster over the AP;
#   * mappings.json / poses.json stay uncompressed (the firmware reads and
#     REWRITES them directly with LittleFS + ArduinoJson);
#   * dev-only 3D models (_test_duck.glb, scene.gltf/bin) are excluded;
#     models/hand.glb IS included if you ever add the real one;
#   * .DS_Store and friends are dropped.
#
# data/ itself is untouched, so `open data/index.html` / a local http.server
# keeps working for UI development.

Import("env")  # noqa: F821  (provided by SCons/PlatformIO)

import gzip
import shutil
from pathlib import Path

SRC = Path(env.subst("$PROJECT_DIR")) / "data"
OUT = Path(env.subst("$PROJECT_BUILD_DIR")) / env.subst("$PIOENV") / "fsdata"

GZIP_EXTS = {".html", ".css", ".js", ".gltf", ".svg", ".map", ".txt"}
KEEP_RAW = {"mappings.json", "poses.json"}          # firmware writes these back
SKIP_NAMES = {".DS_Store", "Thumbs.db"}
SKIP_MODEL_FILES = {"_test_duck.glb", "scene.gltf", "scene.bin", "license.txt"}


def stage():
    if OUT.exists():
        shutil.rmtree(OUT)
    total_in = total_out = 0
    for f in sorted(SRC.rglob("*")):
        if not f.is_file() or f.name in SKIP_NAMES:
            continue
        rel = f.relative_to(SRC)
        if rel.parts[0] == "models" and f.name in SKIP_MODEL_FILES:
            continue
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = f.read_bytes()
        total_in += len(raw)
        if f.suffix.lower() in GZIP_EXTS and f.name not in KEEP_RAW:
            packed = gzip.compress(raw, 9)
            dst = dst.with_name(dst.name + ".gz")
            dst.write_bytes(packed)
            total_out += len(packed)
        else:
            shutil.copy2(f, dst)
            total_out += len(raw)
    print(
        "prep_fs: staged data/ -> %s  (%.0f KB -> %.0f KB)"
        % (OUT, total_in / 1024, total_out / 1024)
    )


stage()
# Point the filesystem image builder at the staged tree.
env.Replace(PROJECT_DATA_DIR=str(OUT))
