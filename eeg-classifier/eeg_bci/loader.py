"""Stage 1 - data discovery and labeling.

Scans ``config.DATA_ROOT`` for any folder named ``Session*`` and discovers
every ``.EDF`` recording inside it. Because the real files on disk are named
inconsistently (``BLINK-DO``, ``QUSAITTE``, ``CLINCH-L`` ...) and differ
between sessions, the label is derived from the *folder structure* (category
folder + side keyword) rather than the filename. Each recording is reduced to
a canonical stem (e.g. ``BLINK01``, ``GLENCHLEFT``) that is a key in
``config.LABEL_MAP``, so downstream code keeps using the spec's label map and
noisy-file set unchanged. Adding ``Session3`` later requires zero code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mne

from eeg_bci import config as cfg

# Silence MNE's verbose EDF chatter; we print our own progress.
mne.set_log_level("ERROR")


@dataclass
class Recording:
    """One EDF recording with its discovered metadata.

    Attributes:
        path: Absolute path to the ``.EDF`` file.
        session: Session folder name, e.g. ``"Session1"``.
        category: Top-level category folder (``Blink`` / ``Bruxissem`` / ``Clinch``).
        side: Resolved side/variant keyword (``single`` / ``double`` / ``multiple``
            / ``left`` / ``right`` / ``bilateral``).
        stem: Canonical stem key into ``config.LABEL_MAP``.
        label: Integer class label (0-4).
        class_name: Human-readable class name.
        noisy: ``True`` if the canonical stem is in ``config.NOISY_FILES``.
    """

    path: Path
    session: str
    category: str
    side: str
    stem: str
    label: int
    class_name: str
    noisy: bool


def _detect_category(parts: list[str]) -> str | None:
    """Return the canonical category for a path, or ``None`` if not recognised.

    Args:
        parts: Lower-cased path components below the session folder.

    Returns:
        ``"Blink"``, ``"Bruxissem"`` or ``"Clinch"``, else ``None``.
    """
    joined = " ".join(parts)
    if "blink" in joined:
        return "Blink"
    if "brux" in joined or "qusai" in joined:   # Session2 uses QUSAI* for bruxism
        return "Bruxissem"
    if "clinch" in joined or "glench" in joined:
        return "Clinch"
    return None


def _detect_side(joined: str) -> str | None:
    """Resolve the side/variant keyword from a path string.

    Order matters: 'bilateral'/'both'/'double' are checked before 'left'/'right'
    so that e.g. ``"01 Single RT"`` resolves to right and ``"03- Bilateral"`` to
    bilateral.

    Args:
        joined: Lower-cased, space-joined path components below the category.

    Returns:
        One of ``bilateral``/``double``/``multiple``/``left``/``right``/``single``,
        or ``None`` if nothing matched.
    """
    # "bileteral"/"bilatral" are real misspellings seen in the folder names; a
    # bare side-less bilateral folder would otherwise be silently dropped.
    if ("bilateral" in joined or "bileteral" in joined or "bilatral" in joined
            or "bilat" in joined or "both" in joined):
        return "bilateral"
    if "double" in joined or "-do" in joined:
        return "double"
    if "multiple" in joined or "triple" in joined or "-tr" in joined:
        return "multiple"
    if "left" in joined or "-lt" in joined or "-l." in joined:
        return "left"
    if "right" in joined or " rt" in joined or "-rt" in joined or "-r." in joined:
        return "right"
    if "single" in joined:
        return "single"
    return None


def _canonical_stem(category: str, side: str) -> str | None:
    """Map (category, side) to a canonical ``LABEL_MAP`` stem.

    Args:
        category: ``Blink`` / ``Bruxissem`` / ``Clinch``.
        side: Resolved side keyword from :func:`_detect_side`.

    Returns:
        A stem key present in ``config.LABEL_MAP``, or ``None`` if the
        combination is not understood.
    """
    if category == "Blink":
        if side == "double":
            return "BLINK02"
        if side == "multiple":
            return "BLINK03"
        # single blink (Session1 "Single", Session2 "Bilateral"/BLINK-SINGLE)
        return "BLINK01"
    if category == "Bruxissem":
        if side in ("bilateral", "double"):
            return "BRUXESDOUBLE"
        if side == "left":
            return "BRUXESLEFT"
        if side == "right":
            return "BRUXESRIGHT"
    if category == "Clinch":
        if side in ("bilateral", "double"):
            return "GLENCHDOUBLE"
        if side == "left":
            return "GLENCHLEFT"
        if side == "right":
            return "GLENCHRIGHT"
    return None


def _classify(edf_path: Path, session_dir: Path) -> Recording | None:
    """Build a :class:`Recording` for one EDF file from its folder path.

    Args:
        edf_path: Path to the ``.EDF`` file.
        session_dir: The owning ``Session*`` directory.

    Returns:
        A populated :class:`Recording`, or ``None`` if the file could not be
        classified (a warning is printed in that case).
    """
    rel_parts = [p.lower() for p in edf_path.relative_to(session_dir).parts]
    category = _detect_category(rel_parts)
    if category is None:
        print(f"  [WARN] could not detect category for {edf_path.name} - skipped")
        return None

    # Search side keywords across all path parts below the category folder.
    joined = " ".join(rel_parts)
    side = _detect_side(joined)
    stem = _canonical_stem(category, side) if side else None
    if stem is None:
        print(f"  [WARN] could not detect side for {edf_path.name} "
              f"(category={category}, side={side}) - skipped")
        return None

    # Stems not in the active taxonomy (e.g. triple_blink, bilateral-bruxism,
    # clinch left/right) are intentionally excluded -- skip them cleanly.
    if stem not in cfg.LABEL_MAP:
        print(f"  [skip] {edf_path.name}: stem {stem} not in active taxonomy")
        return None
    label, class_name = cfg.LABEL_MAP[stem]
    noisy = stem in cfg.NOISY_FILES
    return Recording(
        path=edf_path,
        session=session_dir.name,
        category=category,
        side=side,
        stem=stem,
        label=label,
        class_name=class_name,
        noisy=noisy,
    )


def discover_recordings(data_root: str | Path = cfg.DATA_ROOT) -> list[Recording]:
    """Scan ``data_root`` for ``Session*`` folders and classify every EDF.

    Args:
        data_root: Root directory containing the ``Session*`` folders.

    Returns:
        A list of :class:`Recording`, sorted by session then path. Noisy files
        are included and flagged.
    """
    root = Path(data_root)
    if not root.is_dir():
        raise FileNotFoundError(f"DATA_ROOT not found: {root.resolve()}")

    session_dirs = sorted(p for p in root.glob("Session*") if p.is_dir())
    print(f"[loader] scanning {root.resolve()}")
    print(f"[loader] found {len(session_dirs)} session(s): "
          f"{', '.join(d.name for d in session_dirs)}")

    recordings: list[Recording] = []
    for session_dir in session_dirs:
        edf_files = sorted(
            p for p in session_dir.rglob("*") if p.suffix.lower() == ".edf"
        )
        print(f"[loader] {session_dir.name}: {len(edf_files)} EDF file(s)")
        for edf in edf_files:
            rec = _classify(edf, session_dir)
            if rec is None:
                continue
            tag = " [WARN] flagged as noisy" if rec.noisy else ""
            print(f"    {edf.relative_to(root)}  ->  "
                  f"label {rec.label} ({rec.class_name}){tag}")
            recordings.append(rec)

    print(f"[loader] total usable recordings: {len(recordings)}")
    _print_class_counts(recordings)
    return recordings


def _print_class_counts(recordings: list[Recording]) -> None:
    """Print how many recordings fell into each class label.

    Args:
        recordings: The discovered recordings.
    """
    counts: dict[int, int] = {}
    for rec in recordings:
        counts[rec.label] = counts.get(rec.label, 0) + 1
    print("[loader] class distribution (recordings):")
    for label in sorted(cfg.COMMAND_MAP):
        _, name = cfg.COMMAND_MAP[label]
        class_name = next(
            (c for (l, c) in cfg.LABEL_MAP.values() if l == label), name
        )
        print(f"    label {label} ({class_name}): {counts.get(label, 0)}")


def load_raw(recording: Recording) -> mne.io.BaseRaw:
    """Read a recording's EDF into an MNE Raw object.

    Channels are reordered to match ``config.ALL_CH``. Noisy files are loaded
    anyway and re-flagged with ``[WARN]``.

    Args:
        recording: The recording to load.

    Returns:
        A preloaded :class:`mne.io.BaseRaw`.
    """
    if recording.noisy:
        print(f"[WARN] loading noisy file flagged as noisy: "
              f"{recording.path.name} ({recording.class_name})")
    raw = mne.io.read_raw_edf(recording.path, preload=True, verbose="ERROR")

    # Reorder to the canonical montage where possible (robust to missing chans).
    present = [ch for ch in cfg.ALL_CH if ch in raw.ch_names]
    if present:
        raw.reorder_channels(present)
    return raw


if __name__ == "__main__":
    discover_recordings()
