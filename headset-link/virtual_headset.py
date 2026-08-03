#!/usr/bin/env python3
"""Condition a recorded EEG session into the exact EDF that ``load_edf`` accepts.

``load_edf`` (inference.py) matches channel names by *exact string* against
``config.ALL_CH`` and reorders to it, so the output file must carry the 19
canonical names verbatim, at 200 Hz, with no channel missing.

Subcommands
-----------
check  : read-only montage report on a source EDF. Writes nothing.
build  : normalize -> pick/reorder -> resample -> annotate -> write ready.edf

Heavy libraries (mne, pandas) are imported lazily so ``check`` runs even when
the EDF *export* backend (edfio) is not installed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- #
# Canonical montage
# --------------------------------------------------------------------------- #
# Verbatim from eeg_bci/config.py::ALL_CH. The "-Ref" suffix is part of the
# name load_edf compares against -- writing bare "Fp1" makes load_edf report
# all 19 channels missing.
ALL_CH = [
    "Fp1-Ref", "Fp2-Ref", "Fz-Ref", "F8-Ref", "F7-Ref", "F4-Ref", "F3-Ref",
    "C4-Ref", "C3-Ref", "O2-Ref", "P3-Ref", "Cz-Ref", "O1-Ref", "P4-Ref",
    "Pz-Ref", "T6-Ref", "T5-Ref", "T4-Ref", "T3-Ref",
]

# Electrode label with the reference suffix removed; the unit of matching.
CANONICAL = [name.split("-")[0] for name in ALL_CH]
_CANON_BY_UPPER = {name.upper(): name for name in CANONICAL}

TARGET_SFREQ = 200.0  # config.SFREQ

# Modern 10-10 spellings -> the 10-20 names config.ALL_CH uses.
_MODERN_TO_OLD = {"T7": "T3", "T8": "T4", "P7": "T5", "P8": "T6"}

_PREFIX_RE = re.compile(r"^(?:EEG|POL)\s+", re.IGNORECASE)
_SEP_RE = re.compile(r"[-_ ]")


def output_names(naming: str = "ref") -> list[str]:
    """Names to write into the EDF: config.ALL_CH ("ref") or bare electrodes."""
    return list(ALL_CH) if naming == "ref" else list(CANONICAL)


def normalize_channel(raw_name: str | None) -> str | None:
    """Reduce a source channel name to its canonical electrode, else ``None``.

    Keeps only the token before the first ``-``, ``_`` or space, which is what
    protects ``Cz``: a stripper that instead deleted known reference tokens
    anywhere in the name would eat the real ``Cz`` channel, since ``Cz`` is
    itself a common reference (e.g. ``Fp1-Cz``).
    """
    if raw_name is None:
        return None
    s = raw_name.strip()
    if not s:
        return None
    s = _PREFIX_RE.sub("", s, count=1)
    token = _SEP_RE.split(s, maxsplit=1)[0].strip()
    if not token:
        return None
    key = token.upper()
    key = _MODERN_TO_OLD.get(key, key)
    return _CANON_BY_UPPER.get(key)


@dataclass(frozen=True)
class MontageResult:
    """Outcome of matching a source montage against the canonical 19."""

    mapping: dict[str, str]              # source name -> output name
    renamed: list[tuple[str, str]]       # subset of mapping where name changes
    missing: list[str]                   # output names not found
    ignored: list[str]                   # non-EEG / unrecognized source names
    duplicates: list[tuple[str, str]]    # (source, electrode) dropped as dupes

    @property
    def found(self) -> int:
        return len(self.mapping)

    @property
    def ok(self) -> bool:
        return not self.missing


def resolve_montage(source_names, naming: str = "ref") -> MontageResult:
    """Map source channel names onto the canonical montage."""
    out_names = output_names(naming)
    out_by_canon = dict(zip(CANONICAL, out_names))

    mapping: dict[str, str] = {}
    ignored: list[str] = []
    duplicates: list[tuple[str, str]] = []
    claimed: dict[str, str] = {}  # electrode -> winning source name

    for src in source_names:
        canon = normalize_channel(src)
        if canon is None:
            ignored.append(src)
            continue
        if canon in claimed:
            duplicates.append((src, canon))
            continue
        claimed[canon] = src
        mapping[src] = out_by_canon[canon]

    missing = [out_by_canon[c] for c in CANONICAL if c not in claimed]
    renamed = [
        (claimed[c], out_by_canon[c])
        for c in CANONICAL
        if c in claimed and claimed[c] != out_by_canon[c]
    ]
    return MontageResult(mapping, renamed, missing, ignored, duplicates)


# --------------------------------------------------------------------------- #
# Labels CSV
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Label:
    onset: float
    duration: float
    description: str


_TIME_COLS = ["onset", "onsets", "onsetsec", "onsetseconds", "time", "times",
              "timestamp", "start", "starttime", "begin", "beginning"]
_LABEL_COLS = ["label", "labels", "event", "events", "description", "desc",
               "side", "marker", "annotation", "type", "class", "name",
               "trigger", "condition"]
_DUR_COLS = ["duration", "dur", "length", "len"]
_END_COLS = ["end", "endtime", "stop", "stoptime", "finish", "offset"]


def _norm(col: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(col).lower())


def _numeric_ok(series) -> bool:
    import pandas as pd

    return pd.to_numeric(series, errors="coerce").notna().any()


def _find_col(df, candidates, *, numeric: bool, fuzzy: bool):
    """Exact normalized match first, then a prefix match. ``None`` if no hit."""
    norm_to_real = {}
    for c in df.columns:
        norm_to_real.setdefault(_norm(c), c)

    for cand in candidates:
        real = norm_to_real.get(cand)
        if real is not None and (not numeric or _numeric_ok(df[real])):
            return real
    if not fuzzy:
        return None
    for cand in candidates:
        for norm, real in norm_to_real.items():
            if norm.startswith(cand) and (not numeric or _numeric_ok(df[real])):
                return real
    return None


def parse_labels(
    df,
    *,
    time_unit: str = "s",
    time_col: str | None = None,
    label_col: str | None = None,
    dur_col: str | None = None,
    end_col: str | None = None,
) -> list[Label]:
    """Turn a labels DataFrame into annotations (onset, duration, description).

    Column names vary between exports, so onset/label/duration/end columns are
    auto-detected unless overridden. ``time_unit='ms'`` divides every time
    column by 1000. Duration wins over end; if only end exists, duration is
    ``end - onset``.
    """
    import pandas as pd

    if time_unit not in ("s", "ms"):
        raise ValueError(f"time_unit must be 's' or 'ms', got {time_unit!r}")
    scale = 1000.0 if time_unit == "ms" else 1.0

    for name, col in (("--time-col", time_col), ("--label-col", label_col),
                      ("--dur-col", dur_col), ("--end-col", end_col)):
        if col is not None and col not in df.columns:
            raise ValueError(
                f"{name}={col!r} is not a column in the labels file. "
                f"Columns: {list(df.columns)}")

    tcol = time_col or _find_col(df, _TIME_COLS, numeric=True, fuzzy=True)
    if tcol is None:
        raise ValueError(
            "Could not auto-detect an onset/time column in the labels file "
            f"(columns: {list(df.columns)}). Pass --time-col.")

    lcol = label_col or _find_col(df, _LABEL_COLS, numeric=False, fuzzy=True)
    if lcol is None:
        raise ValueError(
            "Could not auto-detect a label/event column in the labels file "
            f"(columns: {list(df.columns)}). Pass --label-col.")

    dcol = dur_col or _find_col(df, _DUR_COLS, numeric=True, fuzzy=False)
    ecol = end_col or _find_col(df, _END_COLS, numeric=True, fuzzy=False)
    # A column can't be both the onset and the end/duration.
    if dcol == tcol:
        dcol = None
    if ecol == tcol:
        ecol = None

    onset = pd.to_numeric(df[tcol], errors="coerce") / scale
    if dcol is not None:
        duration = pd.to_numeric(df[dcol], errors="coerce") / scale
    elif ecol is not None:
        duration = pd.to_numeric(df[ecol], errors="coerce") / scale - onset
    else:
        duration = onset * 0.0

    labels: list[Label] = []
    for i in range(len(df)):
        o = onset.iloc[i]
        d = duration.iloc[i]
        desc = df[lcol].iloc[i]
        if pd.isna(o) or pd.isna(desc):
            continue
        d = 0.0 if pd.isna(d) else float(d)
        if d < 0:
            d = 0.0
        labels.append(Label(float(o), d, str(desc).strip()))

    if not labels:
        raise ValueError(f"No usable rows in labels file (columns: {list(df.columns)}).")
    labels.sort(key=lambda x: x.onset)
    return labels


def read_labels(path, **kwargs) -> list[Label]:
    """Read a labels CSV from disk and parse it. pandas is imported lazily."""
    import pandas as pd

    df = pd.read_csv(path)
    return parse_labels(df, **kwargs)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _fmt_report(src: Path, n_ch: int, sfreq: float, dur: float,
                res: MontageResult, naming: str) -> str:
    lines = [
        f"Source: {src}",
        f"  channels : {n_ch}",
        f"  sfreq    : {sfreq:g} Hz",
        f"  duration : {dur:.2f} s",
        "",
        f"Montage: {res.found}/19 matched   (target names: "
        f"{'config.ALL_CH, e.g. Fp1-Ref' if naming == 'ref' else 'bare, e.g. Fp1'})",
    ]

    if res.renamed:
        lines.append(f"  renamed ({len(res.renamed)}):")
        width = max(len(s) for s, _ in res.renamed)
        lines += [f"    {s:<{width}} -> {d}" for s, d in res.renamed]
    else:
        lines.append("  renamed (0): none")

    if res.ignored:
        lines.append(f"  ignored non-EEG ({len(res.ignored)}): {', '.join(res.ignored)}")
    if res.duplicates:
        lines.append(
            f"  duplicate electrodes dropped ({len(res.duplicates)}): "
            + ", ".join(f"{s} (={c})" for s, c in res.duplicates))

    if res.missing:
        lines.append(f"  MISSING ({len(res.missing)}): {', '.join(res.missing)}")
    else:
        lines.append("  MISSING (0): none")

    lines.append("")
    if abs(sfreq - TARGET_SFREQ) > 1e-9:
        lines.append(f"Resample: {sfreq:g} Hz -> {TARGET_SFREQ:g} Hz (build will resample)")
    else:
        lines.append(f"Resample: not needed (already {TARGET_SFREQ:g} Hz)")
    lines.append(
        "Verdict: READY to build" if res.ok
        else "Verdict: NOT BUILDABLE - montage incomplete")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def _read_raw(path: Path, preload: bool):
    import mne

    return mne.io.read_raw_edf(path, preload=preload, verbose="ERROR")


def cmd_check(args) -> int:
    src = Path(args.inp)
    if not src.exists():
        print(f"error: EDF not found: {src}", file=sys.stderr)
        return 2

    raw = _read_raw(src, preload=False)
    sfreq = float(raw.info["sfreq"])
    res = resolve_montage(raw.ch_names, naming=args.naming)
    print(_fmt_report(src, len(raw.ch_names), sfreq, raw.n_times / sfreq,
                      res, args.naming))
    return 0 if res.ok else 1


def cmd_build(args) -> int:
    import mne

    src = Path(args.inp)
    out = Path(args.out)
    if not src.exists():
        print(f"error: EDF not found: {src}", file=sys.stderr)
        return 2
    labels_path = Path(args.labels)
    if not labels_path.exists():
        print(f"error: labels CSV not found: {labels_path}", file=sys.stderr)
        return 2

    # Parse labels before touching the EDF: a bad CSV should fail fast.
    labels = read_labels(
        labels_path,
        time_unit=args.time_unit,
        time_col=args.time_col,
        label_col=args.label_col,
        dur_col=args.dur_col,
        end_col=args.end_col,
    )

    raw = _read_raw(src, preload=True)
    res = resolve_montage(raw.ch_names, naming=args.naming)

    # Requirement 5: never write a partial file.
    if res.missing:
        print(
            f"error: {src.name} is missing {len(res.missing)} of the 19 required "
            f"channels after normalization:\n"
            f"  {', '.join(res.missing)}\n"
            f"Found {res.found}/19. Nothing was written.",
            file=sys.stderr,
        )
        return 1

    # Drop extras/duplicates *before* renaming so no rename can collide with an
    # existing source name.
    raw.pick(list(res.mapping.keys()))
    raw.rename_channels(res.mapping)
    raw.reorder_channels(output_names(args.naming))

    sfreq = float(raw.info["sfreq"])
    if abs(sfreq - args.sfreq) > 1e-9:
        print(f"resampling {sfreq:g} Hz -> {args.sfreq:g} Hz")
        raw.resample(args.sfreq)

    dur = raw.n_times / float(raw.info["sfreq"])
    late = [l for l in labels if l.onset >= dur]
    if late:
        print(f"warning: {len(late)} label(s) start at or after the end of the "
              f"recording ({dur:.2f} s) and will be dropped by MNE",
              file=sys.stderr)

    raw.set_annotations(mne.Annotations(
        onset=[l.onset for l in labels],
        duration=[l.duration for l in labels],
        description=[l.description for l in labels],
    ))

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.tmp.edf")
    try:
        mne.export.export_raw(tmp, raw, fmt="edf", overwrite=True, verbose="ERROR")
        os.replace(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    print(f"wrote {out}")
    print(f"  channels    : {len(raw.ch_names)} in config.ALL_CH order")
    print(f"  sfreq       : {raw.info['sfreq']:g} Hz")
    print(f"  duration    : {dur:.2f} s")
    print(f"  annotations : {len(labels)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="virtual_headset.py",
        description="Condition a recorded EEG session into a classifier-ready EDF.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--in", dest="inp", required=True, metavar="SESSION.EDF")
    common.add_argument("--naming", choices=["ref", "bare"], default="ref",
                        help="output channel names: 'ref' = config.ALL_CH "
                             "(Fp1-Ref, default), 'bare' = Fp1")

    c = sub.add_parser("check", parents=[common],
                       help="read-only montage report; writes nothing")
    c.set_defaults(func=cmd_check)

    b = sub.add_parser("build", parents=[common], help="write the classifier-ready EDF")
    b.add_argument("--labels", required=True, metavar="LABELS.CSV")
    b.add_argument("--out", required=True, metavar="READY.EDF")
    b.add_argument("--time-unit", choices=["s", "ms"], default="s",
                   help="unit of the time columns in the labels CSV (default: s)")
    b.add_argument("--time-col", default=None, help="override onset column name")
    b.add_argument("--label-col", default=None, help="override label column name")
    b.add_argument("--dur-col", default=None, help="override duration column name")
    b.add_argument("--end-col", default=None, help="override end column name")
    b.add_argument("--sfreq", type=float, default=TARGET_SFREQ,
                   help=f"target sample rate (default: {TARGET_SFREQ:g})")
    b.set_defaults(func=cmd_build)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ImportError as exc:
        print(f"error: missing dependency: {exc}\n"
              f"hint: EDF export needs the edfio backend (pip install edfio)",
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
