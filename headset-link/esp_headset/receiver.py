"""Classifier side (RPi5): turn a received segment into confirmed commands.

The bridge is deliberately thin. ``inference.py`` is not modified: this module
rebuilds an ``mne.io.RawArray`` carrying the canonical montage and hands it to
the very same ``preprocess_stream`` -> ``stream_windows`` -> ``CommandFSM`` path
that ``inference.stream_file`` uses on an EDF.

One consequence of that fidelity is worth stating plainly: ``preprocess_stream``
band-passes with a 3.31 s kernel and z-scores each channel over the *whole*
signal, so a segment is classified once it has fully arrived, not sample by
sample. Playback is real-time; inference is per-segment.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import protocol
from .protocol import Header
from .transport import Transport

_CHUNK = 65536


@dataclass(frozen=True)
class Fire:
    """A command the FSM confirmed, mirroring ``inference.stream_file``."""

    t: float
    label: int
    name: str
    conf: float
    char: str
    action: str


def recv_segment(transport: Transport) -> tuple[Header, np.ndarray]:
    """Read one header + payload off the link. Returns ``(header, int16 counts)``."""
    header = protocol.decode_header(transport.recv_exactly(protocol.HEADER_SIZE))
    remaining = header.payload_nbytes
    parts = []
    while remaining:
        part = transport.recv_exactly(min(remaining, _CHUNK))
        parts.append(part)
        remaining -= len(part)
    return header, protocol.decode_samples(b"".join(parts), header.n_ch)


class Classifier:
    """Loads the trained pipeline once, then classifies each arriving segment."""

    def __init__(self, project: str | Path, model: str = "dtw") -> None:
        self.project = Path(project).resolve()
        if str(self.project) not in sys.path:
            sys.path.insert(0, str(self.project))

        import eeg_bci.config as cfg
        import inference

        self.cfg = cfg
        self.inference = inference
        # Model paths in config are relative to the project root.
        self.predictor = inference.load_predictor(model, self.project / cfg.DTW_HYBRID_MODEL_PATH
                                                  if model == "dtw" else None)

    def to_raw(self, counts: np.ndarray, header: Header):
        """Wrap digital counts in a RawArray with the canonical montage."""
        import mne

        if counts.shape[0] != len(self.cfg.ALL_CH):
            raise ValueError(f"expected {len(self.cfg.ALL_CH)} channels, got {counts.shape[0]}")
        volts = protocol.counts_to_volts(counts, header.scale_uv_per_lsb, header.offset_uv)
        info = mne.create_info(list(self.cfg.ALL_CH), header.sfreq, ch_types="eeg")
        return mne.io.RawArray(volts, info, verbose="ERROR")

    def fire(self, counts: np.ndarray, header: Header) -> list[Fire]:
        """Run the segment through the real inference path; return confirmed commands."""
        cfg, inf = self.cfg, self.inference
        raw = self.to_raw(counts, header)
        data_uv, data_norm = inf.preprocess_stream(raw)

        fsm = inf.CommandFSM()
        fires: list[Fire] = []
        for res in inf.stream_windows(data_uv, data_norm, self.predictor):
            if res["status"] != "ok":       # rest or low_conf: a break in the streak
                fsm.reset()
                continue
            if fsm.update(res["label"]):
                char, action = cfg.COMMAND_MAP[res["label"]]
                fires.append(Fire(res["t"], res["label"], res["name"],
                                  res["conf"], char, action))
        return fires


def serve(transport: Transport, classifier: Classifier, *, sender=None) -> list[Fire]:
    """Receive one segment, classify it, optionally push commands to the Arduino."""
    header, counts = recv_segment(transport)
    print(f"[rx] class_id={header.class_id} {header.seconds:.1f}s "
          f"{header.n_ch}ch @ {header.sfreq}Hz ({header.payload_nbytes:,} B)")

    fires = classifier.fire(counts, header)
    for f in fires:
        print(f"[t={f.t:05.1f}s] COMMAND {f.char} - {f.action}  ({f.name}, conf {f.conf:.2f})")
        if sender is not None:
            sender.send(f.char)
    if not fires:
        print("[rx] no command confirmed")

    # Tell the headset what we decided. It only displays this; it never classifies.
    # A headset that hangs up first is fine -- the classification already happened.
    try:
        transport.send(protocol.encode_result({"class_id": header.class_id, "fires": [
            {"t": round(f.t, 2), "label": f.label, "name": f.name,
             "conf": round(f.conf, 3), "char": f.char, "action": f.action} for f in fires]}))
    except (OSError, ConnectionError):
        pass
    return fires


def _main(argv=None) -> int:
    import argparse

    from .transport import rfcomm_listen, tcp_listen

    ap = argparse.ArgumentParser(
        prog="python -m esp_headset.receiver",
        description="Listen for a virtual-headset segment and emit BCI commands.")
    ap.add_argument("--project", required=True, help="EEG_GRADUATIO_PROJECT root")
    ap.add_argument("--model", default="dtw")
    ap.add_argument("--port", type=int, default=5005,
                    help="TCP port (not 5000: macOS AirPlay Receiver listens there)")
    ap.add_argument("--rfcomm", type=int, metavar="CHANNEL",
                    help="use Bluetooth SPP on this RFCOMM channel instead of TCP (Linux)")
    ap.add_argument("--serial-port", default=None, help="Arduino port (default: config)")
    ap.add_argument("--no-serial", action="store_true", help="print commands, never open a port")
    ap.add_argument("--once", action="store_true", help="handle one segment and exit")
    args = ap.parse_args(argv)

    clf = Classifier(args.project, model=args.model)
    ser = clf.inference.SerialSender(args.serial_port or clf.cfg.SERIAL_PORT,
                                     enabled=not args.no_serial)
    while True:
        where = f"RFCOMM ch {args.rfcomm}" if args.rfcomm else f"TCP :{args.port}"
        print(f"[rx] waiting for headset on {where} ...")
        link = rfcomm_listen(args.rfcomm) if args.rfcomm else tcp_listen(args.port)
        with link:
            serve(link, clf, sender=ser)
        if args.once:
            return 0


if __name__ == "__main__":
    raise SystemExit(_main())
