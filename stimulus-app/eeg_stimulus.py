"""
EEG Stimulus Presentation — Simplified (9 classes)
==================================================
Single-file tkinter app. Optional: pygame (audio fallback only).

Run:  python eeg_stimulus.py

Two recording modes:
  • TRAIN  — record ONE class repeatedly (one file per class) for model training.
  • TEST   — record a random MIX of all 9 classes in one file for evaluation.

The 9 classes (marker_id):
  1 single_blink        2 double_blink        3 triple_blink
  4 jaw_clench_both     5 jaw_clench_right    6 jaw_clench_left
  7 bruxism_both        8 bruxism_right       9 bruxism_left

Outputs are written to ./recordings/ as a markers CSV + a summary TXT.
"""

import os
import csv
import sys
import time
import math
import glob
import re
import random
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ----------------------------------------------------------------------
# Colors
# ----------------------------------------------------------------------
BG = "#000000"
FG = "#ffffff"
ACCENT = "#00d4ff"
OK = "#00ff88"
WARN = "#ff5566"

# ----------------------------------------------------------------------
# The 9 classes.  (key, marker_id, title, arabic, emoji, instruction, action)
# marker_id is fixed and stable so EEG/EDF alignment never shifts.
# ----------------------------------------------------------------------
CLASSES = [
    ("single_blink",     1, "Single Blink",      "رمشة واحدة",        "👁",   "Blink ONCE, naturally.",                 "BLINK ×1"),
    ("double_blink",     2, "Double Blink",      "رمشتان متتاليتان",   "👁👁",  "Blink TWICE quickly (~200 ms apart).",   "BLINK ×2"),
    ("triple_blink",     3, "Triple Blink",      "ثلاث رمشات",        "👁✨",  "Blink THREE times rapidly.",             "BLINK ×3"),
    ("jaw_clench_both",  4, "Jaw Clench BOTH",   "اضغط الفكين",        "🦷",   "Clench teeth on BOTH sides. Hold.",      "CLENCH BOTH"),
    ("jaw_clench_right", 5, "Jaw Clench RIGHT",  "اضغط الفك الأيمن",   "🦷➡",  "Clench the RIGHT side only. Hold.",      "CLENCH RIGHT"),
    ("jaw_clench_left",  6, "Jaw Clench LEFT",   "اضغط الفك الأيسر",   "🦷⬅",  "Clench the LEFT side only. Hold.",       "CLENCH LEFT"),
    ("bruxism_both",     7, "Bruxism BOTH",      "صرير الأسنان",       "😬",   "Grind teeth, BOTH sides. Hold.",         "GRIND BOTH"),
    ("bruxism_right",    8, "Bruxism RIGHT",     "صرير يمين",          "😬➡",  "Grind on the RIGHT side. Hold.",         "GRIND RIGHT"),
    ("bruxism_left",     9, "Bruxism LEFT",      "صرير يسار",          "😬⬅",  "Grind on the LEFT side. Hold.",          "GRIND LEFT"),
]

# Lookup by key
CLASS_INFO = {
    key: {"key": key, "marker_id": mid, "title": title, "arabic": ar,
          "emoji": em, "instruction": ins, "action": act}
    for (key, mid, title, ar, em, ins, act) in CLASSES
}
CLASS_KEYS = [c[0] for c in CLASSES]

# Reserved marker for the inter-trial rest / baseline
MARKER_REST = 0

# ----------------------------------------------------------------------
# Audio cues (macOS afplay / Windows winsound / pygame fallback)
# ----------------------------------------------------------------------
_AUDIO_OK = False
try:
    import pygame
    pygame.mixer.init()
    _AUDIO_OK = True
except Exception:
    _AUDIO_OK = False

_SOUND_ENABLED = True
_MAC_SOUND_DIR = "/System/Library/Sounds"
_MAC_SOUNDS = {
    "start": "Hero.aiff", "end": "Glass.aiff", "cue": "Tink.aiff",
    "go": "Ping.aiff", "stop": "Pop.aiff", "break": "Submarine.aiff",
    "stopall": "Sosumi.aiff", "reject": "Basso.aiff",
}
_WIN_SOUNDS = {
    "start": (523, 250), "end": (392, 400), "cue": (880, 80),
    "go": (1175, 120), "stop": (660, 150), "break": (440, 350),
    "stopall": (220, 600), "reject": (175, 200),
}


def play_sound(kind="cue"):
    if not _SOUND_ENABLED:
        return
    try:
        if sys.platform == "darwin":
            f = os.path.join(_MAC_SOUND_DIR, _MAC_SOUNDS.get(kind, "Tink.aiff"))
            if os.path.exists(f):
                subprocess.Popen(["afplay", f], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return
        elif sys.platform == "win32":
            import winsound
            freq, dur = _WIN_SOUNDS.get(kind, (880, 120))
            threading.Thread(target=lambda: winsound.Beep(freq, dur),
                             daemon=True).start()
            return
    except Exception:
        pass
    if _AUDIO_OK:
        try:
            import array
            sr, dur, freq = 22050, 0.12, 880
            n = int(sr * dur)
            buf = array.array("h",
                [int(16000 * math.sin(2 * math.pi * freq * i / sr)) for i in range(n)])
            pygame.mixer.Sound(buffer=buf.tobytes()).play()
        except Exception:
            pass


# ----------------------------------------------------------------------
# StyledButton — canvas-based so colors render on every platform
# (macOS Aqua overrides tk.Button colors otherwise).
# ----------------------------------------------------------------------
class StyledButton(tk.Canvas):
    def __init__(self, parent, text, command,
                 bg="#005577", hover="#0088aa", fg="white",
                 padx=18, pady=10, font=("Helvetica", 12, "bold"), width=None):
        import tkinter.font as tkfont
        f = tkfont.Font(family=font[0], size=font[1],
                        weight=font[2] if len(font) > 2 else "normal")
        cw = (width if width else f.measure(text)) + padx * 2
        ch = f.metrics("linespace") + pady * 2
        super().__init__(parent, width=cw, height=ch, bg=bg,
                         highlightthickness=2, highlightbackground=hover,
                         highlightcolor=hover, bd=0, cursor="hand2")
        self._normal, self._hover, self._cmd = bg, hover, command
        self._rect = self.create_rectangle(0, 0, cw, ch, fill=bg, outline="")
        self._txt = self.create_text(cw // 2, ch // 2, text=text, fill=fg, font=f)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._set(self._hover))
        self.bind("<Leave>", lambda e: self._set(self._normal))

    def _click(self, _e=None):
        self._set("#ffffff")
        self.after(60, lambda: self._set(self._hover))
        if self._cmd:
            self._cmd()

    def _set(self, c):
        self.itemconfigure(self._rect, fill=c)
        self.configure(bg=c)

    def set_text(self, t):
        self.itemconfigure(self._txt, text=t)

    def set_colors(self, bg, hover=None, fg=None):
        self._normal = bg
        if hover:
            self._hover = hover
        if fg:
            self.itemconfigure(self._txt, fill=fg)
        self._set(bg)


# ======================================================================
# Main Application
# ======================================================================
class EEGApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EEG Stimulus — 9 Classes")
        self.geometry("1000x720")
        self.minsize(880, 600)
        self.configure(bg=BG)

        # Session config (shared defaults)
        self.cfg = {
            "subject_id": "S001",
            "mode": "train",          # "train" or "test"
            "train_class": "single_blink",
            "trials": 20,             # train: trials of the class | test: trials PER class
            "cue_dur": 2.0,           # seconds the prompt is shown before GO
            "active_dur": 2.0,        # seconds to perform the action
            "rest_dur": 3.0,          # seconds of rest between trials
            "audio_on": True,
            "fullscreen": True,
            "break_every": 30,        # short break every N trials (0 = never)
        }

        self.markers = []
        self.results = {}             # key -> {"trials","accepted","rejected"}
        self.stim_window = None

        self._build_style()
        self.container = tk.Frame(self, bg=BG)
        self.container.pack(fill="both", expand=True)
        self.current_frame = None
        self.show_setup()

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TProgressbar", background=ACCENT, troughcolor="#222")
        style.configure("Treeview", background="#0a0a0a", fieldbackground="#0a0a0a",
                        foreground=FG, rowheight=24)
        style.configure("Treeview.Heading", background="#1a1a1a", foreground=ACCENT)

    def _swap(self, builder):
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = builder(self.container)
        self.current_frame.pack(fill="both", expand=True)

    # ==================================================================
    # SCREEN 1: Setup
    # ==================================================================
    def show_setup(self):
        self._swap(self._build_setup)

    def _build_setup(self, parent):
        frame = tk.Frame(parent, bg=BG)

        tk.Label(frame, text="EEG Recording Setup", font=("Segoe UI", 26, "bold"),
                 bg=BG, fg=ACCENT).pack(pady=(20, 2))
        tk.Label(frame, text="9 classes  ·  individual TRAIN files  ·  one mixed TEST file",
                 font=("Segoe UI", 11), bg=BG, fg="#aaa").pack(pady=(0, 14))

        # --- Mode toggle ---
        modef = tk.Frame(frame, bg=BG)
        modef.pack(pady=(0, 8))
        self.mode_var = tk.StringVar(value=self.cfg["mode"])

        self.btn_train = StyledButton(modef, "🎯  TRAIN  (one class)",
                                      lambda: self._set_mode("train"),
                                      font=("Segoe UI", 13, "bold"), padx=22, pady=12)
        self.btn_train.pack(side="left", padx=8)
        self.btn_test = StyledButton(modef, "🎲  TEST  (random mix)",
                                     lambda: self._set_mode("test"),
                                     font=("Segoe UI", 13, "bold"), padx=22, pady=12)
        self.btn_test.pack(side="left", padx=8)

        # --- Form ---
        form = tk.Frame(frame, bg="#0a0a0a", padx=24, pady=18)
        form.pack(padx=40, pady=10, fill="x")

        self._auto_run_number()
        self.fields = {}

        def add_entry(row, key, label):
            tk.Label(form, text=label + ":", anchor="e", width=22, font=("Segoe UI", 12),
                     bg="#0a0a0a", fg=FG).grid(row=row, column=0, sticky="e", pady=6, padx=8)
            v = tk.StringVar(value=str(self.cfg[key]))
            e = tk.Entry(form, textvariable=v, width=12, bd=0, font=("Consolas", 13),
                         bg="#1a1a1a", fg=FG, insertbackground=FG)
            e.grid(row=row, column=1, sticky="w", pady=6, padx=8)
            e.bind("<KeyRelease>", lambda _e: self._update_preview())
            self.fields[key] = v

        add_entry(0, "subject_id", "Subject ID")
        # trials label text changes with mode
        self.trials_label = tk.Label(form, text="", anchor="e", width=22,
                                     font=("Segoe UI", 12), bg="#0a0a0a", fg=FG)
        self.trials_label.grid(row=1, column=0, sticky="e", pady=6, padx=8)
        v = tk.StringVar(value=str(self.cfg["trials"]))
        e = tk.Entry(form, textvariable=v, width=12, bd=0, font=("Consolas", 13),
                     bg="#1a1a1a", fg=FG, insertbackground=FG)
        e.grid(row=1, column=1, sticky="w", pady=6, padx=8)
        e.bind("<KeyRelease>", lambda _e: self._update_preview())
        self.fields["trials"] = v

        add_entry(2, "cue_dur", "Cue / prompt (s)")
        add_entry(3, "active_dur", "Action duration (s)")
        add_entry(4, "rest_dur", "Rest between trials (s)")
        add_entry(5, "break_every", "Break every N trials")

        # Toggles
        self.audio_var = tk.BooleanVar(value=self.cfg["audio_on"])
        self.fs_var = tk.BooleanVar(value=self.cfg["fullscreen"])
        tgl = tk.Frame(form, bg="#0a0a0a")
        tgl.grid(row=6, column=0, columnspan=2, pady=(10, 0))
        self._make_toggle(tgl, "Audio cues", self.audio_var)
        self._make_toggle(tgl, "Fullscreen", self.fs_var)

        # --- Class picker (only relevant in TRAIN mode) ---
        self.picker_frame = tk.Frame(frame, bg=BG)
        self.picker_frame.pack(pady=(8, 4))
        self.class_var = tk.StringVar(value=self.cfg["train_class"])
        self.class_buttons = {}
        tk.Label(self.picker_frame, text="Class to record:", bg=BG, fg="#aaa",
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, pady=(0, 6))
        for i, (key, mid, title, ar, em, ins, act) in enumerate(CLASSES):
            b = StyledButton(self.picker_frame, f"{em}  {mid}. {title}",
                             lambda k=key: self._pick_class(k),
                             bg="#1f3a4a", hover="#2a5070",
                             font=("Segoe UI", 11, "bold"), padx=10, pady=8, width=210)
            b.grid(row=1 + i // 3, column=i % 3, padx=5, pady=4)
            self.class_buttons[key] = b

        # --- Preview ---
        self.preview_label = tk.Label(frame, text="", font=("Segoe UI", 14, "bold"),
                                      bg=BG, fg=OK)
        self.preview_label.pack(pady=(8, 4))

        # --- Start ---
        StyledButton(frame, "▶   Start Recording", self._start,
                     bg="#006644", hover="#00aa66",
                     font=("Segoe UI", 15, "bold"), padx=30, pady=14).pack(pady=10)

        self._set_mode(self.cfg["mode"])
        self._pick_class(self.cfg["train_class"])
        self._update_preview()
        return frame

    def _make_toggle(self, parent, label, var):
        holder = tk.Frame(parent, bg="#0a0a0a")
        holder.pack(side="left", padx=14)
        tk.Label(holder, text=label, bg="#0a0a0a", fg=FG,
                 font=("Segoe UI", 11)).pack(side="left", padx=(0, 6))
        btn = StyledButton(holder, "", lambda: None, width=70, padx=10, pady=4)

        def refresh():
            if var.get():
                btn.set_text("● ON"); btn.set_colors("#006644", "#00aa66", "white")
            else:
                btn.set_text("○ OFF"); btn.set_colors("#552222", "#aa3333", "white")

        def toggle():
            var.set(not var.get()); refresh(); self._update_preview()

        btn._cmd = toggle
        refresh()
        btn.pack(side="left")

    def _set_mode(self, mode):
        self.cfg["mode"] = mode
        self.mode_var.set(mode)
        if mode == "train":
            self.btn_train.set_colors("#006644", "#00aa66", "white")
            self.btn_test.set_colors("#333333", "#555555", "white")
            self.trials_label.config(text="Trials (this class):")
            self.picker_frame.pack(pady=(8, 4))
        else:
            self.btn_test.set_colors("#006644", "#00aa66", "white")
            self.btn_train.set_colors("#333333", "#555555", "white")
            self.trials_label.config(text="Trials PER class:")
            self.picker_frame.pack_forget()
        self._auto_run_number()
        self._update_preview()

    def _pick_class(self, key):
        self.cfg["train_class"] = key
        self.class_var.set(key)
        for k, b in self.class_buttons.items():
            if k == key:
                b.set_colors("#006644", "#00aa66", "white")
            else:
                b.set_colors("#1f3a4a", "#2a5070", "white")
        if self.cfg["mode"] == "train":
            self._auto_run_number()
        self._update_preview()

    def _read_form(self):
        try:
            c = dict(self.cfg)
            c["subject_id"] = self.fields["subject_id"].get().strip() or "S001"
            c["trials"] = max(1, int(self.fields["trials"].get()))
            c["cue_dur"] = max(0.2, float(self.fields["cue_dur"].get()))
            c["active_dur"] = max(0.2, float(self.fields["active_dur"].get()))
            c["rest_dur"] = max(0.2, float(self.fields["rest_dur"].get()))
            c["break_every"] = max(0, int(self.fields["break_every"].get()))
            c["audio_on"] = bool(self.audio_var.get())
            c["fullscreen"] = bool(self.fs_var.get())
            c["mode"] = self.cfg["mode"]
            c["train_class"] = self.cfg["train_class"]
            return c
        except Exception:
            return None

    def _update_preview(self):
        c = self._read_form()
        if c is None:
            self.preview_label.config(text="(check numeric fields)")
            return
        if c["mode"] == "train":
            total = c["trials"]
            what = f"class: {CLASS_INFO[c['train_class']]['title']}"
        else:
            total = c["trials"] * len(CLASSES)
            what = f"{len(CLASSES)} classes × {c['trials']}"
        per_trial = c["cue_dur"] + c["active_dur"] + c["rest_dur"]
        mins = total * per_trial / 60.0
        self.preview_label.config(
            text=f"{what}    |    total trials: {total}    |    ~{mins:.1f} min")

    # ==================================================================
    # Start session
    # ==================================================================
    def _start(self):
        c = self._read_form()
        if c is None:
            messagebox.showerror("Invalid", "Please check the numeric fields.")
            return
        self.cfg = c
        global _SOUND_ENABLED
        _SOUND_ENABLED = bool(c["audio_on"])

        # Build the trial list
        if c["mode"] == "train":
            self.trial_list = [c["train_class"]] * c["trials"]
            self.active_keys = [c["train_class"]]
        else:
            trials = []
            for k in CLASS_KEYS:
                trials += [k] * c["trials"]
            random.shuffle(trials)
            trials = self._fix_repeats(trials)
            self.trial_list = trials
            self.active_keys = list(CLASS_KEYS)

        self.markers = []
        self.results = {k: {"trials": 0, "accepted": 0, "rejected": 0}
                        for k in self.active_keys}
        self._launch_stimulus()
        play_sound("start")

    def _fix_repeats(self, trials):
        """Best-effort: avoid back-to-back identical trials."""
        if len(trials) < 2:
            return trials
        out = trials[:]
        for i in range(1, len(out)):
            if out[i] == out[i - 1]:
                for j in range(i + 1, len(out)):
                    if out[j] != out[i - 1] and (j + 1 >= len(out) or out[j + 1] != out[i]):
                        out[i], out[j] = out[j], out[i]
                        break
        return out

    # ==================================================================
    # SCREEN 2: Stimulus presentation
    # ==================================================================
    def _launch_stimulus(self):
        c = self.cfg
        self.trial_index = 0
        self.paused = False
        self.stop_requested = False
        self.skip_requested = False
        self.last_trial_rejected = False
        self.last_break_at = -1
        self.session_start_time = time.time()

        win = tk.Toplevel(self)
        self.stim_window = win
        win.configure(bg=BG)
        win.title("EEG Stimulus — Running")
        if c["fullscreen"]:
            try:
                win.attributes("-fullscreen", True)
            except Exception:
                win.state("zoomed")
        else:
            win.geometry("1200x800")
        win.protocol("WM_DELETE_WINDOW", self._confirm_stop)

        # Top bar
        topbar = tk.Frame(win, bg="#0a0a0a", height=54)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)
        self.top_label = tk.Label(topbar, text="", bg="#0a0a0a", fg=FG,
                                  font=("Consolas", 13, "bold"), pady=8)
        self.top_label.pack(side="left", padx=16)

        ctrl = tk.Frame(topbar, bg="#0a0a0a")
        ctrl.pack(side="right", padx=10, pady=4)
        self.btn_pause = StyledButton(ctrl, "⏸  PAUSE", self._toggle_pause,
                                      bg="#665500", hover="#aa8800",
                                      font=("Segoe UI", 11, "bold"), padx=14, pady=6)
        self.btn_pause.pack(side="left", padx=4)
        StyledButton(ctrl, "■  STOP", self._confirm_stop,
                     bg="#aa0000", hover="#ff2222",
                     font=("Segoe UI", 11, "bold"), padx=14, pady=6).pack(side="left", padx=4)

        # Progress (maximum == number of trials; value == completed trials)
        self.progress = ttk.Progressbar(win, mode="determinate",
                                        maximum=len(self.trial_list), value=0)
        self.progress.pack(fill="x")

        # Center canvas
        self.center = tk.Frame(win, bg=BG)
        self.center.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.center, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Bottom log + hint
        logf = tk.Frame(win, bg="#080808", height=92)
        logf.pack(fill="x", side="bottom")
        logf.pack_propagate(False)
        tk.Label(logf, text="Recent markers", bg="#080808", fg="#888",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(4, 0))
        self.log_text = tk.Label(logf, text="", bg="#080808", fg="#aaffaa",
                                 font=("Consolas", 10), justify="left", anchor="nw")
        self.log_text.pack(fill="both", expand=True, padx=12, pady=2)
        tk.Label(win, text="SPACE = pause   ·   R = reject trial   ·   N = skip   ·   ESC = stop   ·   F11 = fullscreen",
                 bg="#050505", fg="#666", font=("Segoe UI", 9), pady=4).pack(fill="x", side="bottom")

        # Keys
        win.bind("<space>", lambda e: self._toggle_pause())
        win.bind("<Escape>", lambda e: self._confirm_stop())
        win.bind("r", lambda e: self._mark_reject())
        win.bind("R", lambda e: self._mark_reject())
        win.bind("n", lambda e: self._skip_trial())
        win.bind("N", lambda e: self._skip_trial())
        win.bind("<F11>", lambda e: self._toggle_fs())
        win.focus_set()

        # Start the loop in "rest" with a short settle period
        self.current_phase = "rest"
        self.phase_start = time.time()
        self.phase_end = self.phase_start + 1.5
        self._update_loop()

    def _toggle_fs(self):
        try:
            cur = self.stim_window.attributes("-fullscreen")
            self.stim_window.attributes("-fullscreen", not cur)
        except Exception:
            pass

    def _toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.pause_started = time.time()
            self.btn_pause.set_text("▶  RESUME")
            self.btn_pause.set_colors("#006644", "#00aa66")
        else:
            self.phase_end += time.time() - self.pause_started
            self.btn_pause.set_text("⏸  PAUSE")
            self.btn_pause.set_colors("#665500", "#aa8800")

    def _confirm_stop(self):
        if messagebox.askyesno("Stop", "Stop the recording?\n\nMarkers so far will be saved.",
                               parent=self.stim_window):
            play_sound("stopall")
            self.stop_requested = True

    def _mark_reject(self):
        if self.current_phase == "active":
            self.last_trial_rejected = True
            play_sound("reject")
            self._log(f"  ⚠ rejected trial {self.trial_index + 1}")

    def _skip_trial(self):
        self.skip_requested = True

    def _log(self, line):
        lines = [x for x in (self.log_text.cget("text").split("\n") + [line]) if x][-4:]
        self.log_text.config(text="\n".join(lines))

    def _write_marker(self, key, trial_num, accepted, duration):
        t_rel = time.time() - self.session_start_time
        self.markers.append({
            "time_sec": round(t_rel, 3),
            "marker_id": CLASS_INFO[key]["marker_id"],
            "signal_name": key,
            "trial_num": trial_num,
            "accepted": accepted,
            "duration_sec": round(duration, 3),
        })
        self._log(f"[{t_rel:7.2f}s] id={CLASS_INFO[key]['marker_id']:>2} "
                  f"{key:<18} trial={trial_num} {'OK' if accepted else 'REJ'}")

    # ---- Main timed loop ----
    def _update_loop(self):
        if self.stop_requested:
            self._end_session(cancelled=True)
            return
        if self.paused:
            self._render_paused()
            self.stim_window.after(100, self._update_loop)
            return
        if self.skip_requested:
            self.skip_requested = False
            self.current_phase = "rest"
            self.phase_start = time.time()
            self.phase_end = self.phase_start + self.cfg["rest_dur"]

        now = time.time()
        c = self.cfg

        if now >= self.phase_end:
            if self.current_phase == "rest":
                # All trials done?
                if self.trial_index >= len(self.trial_list):
                    self._end_session(cancelled=False)
                    return
                # Break? Trigger ONCE per threshold (guarded by last_break_at).
                be = c["break_every"]
                if be > 0 and self.trial_index > 0 and self.trial_index % be == 0 \
                        and self.trial_index != self.last_break_at:
                    self.last_break_at = self.trial_index
                    play_sound("break")
                    self._show_break()
                    return
                # Rest -> cue
                self.current_phase = "cue"
                self.phase_start = now
                self.phase_end = now + c["cue_dur"]
                play_sound("cue")
            elif self.current_phase == "cue":
                # Cue -> active : log marker at action onset
                key = self.trial_list[self.trial_index]
                self.last_trial_rejected = False
                self.current_phase = "active"
                self.phase_start = now
                self.phase_end = now + c["active_dur"]
                play_sound("go")
                self._write_marker(key, self.trial_index + 1, True, c["active_dur"])
            elif self.current_phase == "active":
                # Active -> rest : finalize trial result
                play_sound("stop")
                key = self.trial_list[self.trial_index]
                if self.last_trial_rejected:
                    if self.markers:
                        self.markers[-1]["accepted"] = False
                    self.results[key]["rejected"] += 1
                else:
                    self.results[key]["accepted"] += 1
                self.results[key]["trials"] += 1
                self.trial_index += 1
                self.current_phase = "rest"
                self.phase_start = now
                self.phase_end = now + c["rest_dur"]

        self._render_current()
        self.stim_window.after(50, self._update_loop)

    # ---- Rendering ----
    def _render_paused(self):
        self.canvas.delete("all")
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.create_text(w // 2, h // 2, text="⏸  PAUSED",
                                fill="#ffaa00", font=("Segoe UI", 80, "bold"))
        self.canvas.create_text(w // 2, h // 2 + 90, text="Press SPACE to resume",
                                fill="#888", font=("Segoe UI", 18))

    def _render_current(self):
        c = self.cfg
        elapsed = int(time.time() - self.session_start_time)
        m, s = divmod(elapsed, 60)
        key = self.trial_list[self.trial_index] if self.trial_index < len(self.trial_list) else None
        info = CLASS_INFO.get(key)
        title = info["title"].upper() if info else "—"
        self.top_label.config(
            text=f"{c['subject_id']}  |  {c['mode'].upper()}  |  "
                 f"Trial: {min(self.trial_index + 1, len(self.trial_list))}/{len(self.trial_list)}  |  "
                 f"{title}  |  {self.current_phase.upper()}  |  {m}:{s:02d}")
        self.progress["value"] = self.trial_index

        self.canvas.delete("all")
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            return

        if self.current_phase == "rest" or info is None:
            phase = time.time() - self.phase_start
            size = int(220 * (1.0 + 0.10 * math.sin(phase * 3.0)))
            self.canvas.create_text(w // 2, h // 2, text="+", fill="#ffffff",
                                    font=("Segoe UI", max(40, size), "bold"))

        elif self.current_phase == "cue":
            self.canvas.create_text(w // 2, h // 2 - 180, text=info["emoji"],
                                    fill=ACCENT, font=("Segoe UI Emoji", 150, "bold"))
            self.canvas.create_text(w // 2, h // 2 - 30, text=info["title"].upper(),
                                    fill="#ffffff", font=("Segoe UI", 64, "bold"))
            self.canvas.create_text(w // 2, h // 2 + 50, text=info["arabic"],
                                    fill="#ffcc66", font=("Segoe UI", 42))
            self.canvas.create_text(w // 2, h // 2 + 110, text=info["instruction"],
                                    fill="#aaaaaa", font=("Segoe UI", 18))
            # countdown ring
            remaining = max(0, self.phase_end - time.time())
            frac = remaining / max(0.001, c["cue_dur"])
            cx, cy, r = w // 2, h // 2 + 210, 70
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#333", width=9)
            color = "#ff8844" if remaining <= 1.0 else ACCENT
            self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=90,
                                   extent=-360 * frac, style="arc", outline=color, width=9)
            self.canvas.create_text(cx, cy, text=str(max(1, int(math.ceil(remaining)))),
                                    fill=color, font=("Helvetica", 48, "bold"))

        elif self.current_phase == "active":
            self.canvas.create_text(w // 2, h // 2 - 100, text=info["emoji"],
                                    fill=OK, font=("Segoe UI Emoji", 170, "bold"))
            self.canvas.create_text(w // 2, h // 2 + 70, text=info["action"],
                                    fill=OK, font=("Segoe UI", 90, "bold"))
            self.canvas.create_text(w // 2, h // 2 + 175, text="GO!",
                                    fill="#ffffff", font=("Segoe UI", 40, "bold"))

    # ---- Break overlay ----
    def _show_break(self):
        overlay = tk.Frame(self.center, bg="#0a0a14")
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Label(overlay, text="Break Time!", font=("Segoe UI", 64, "bold"),
                 bg="#0a0a14", fg=ACCENT).pack(pady=(50, 6))
        tk.Label(overlay, text=f"{self.trial_index}/{len(self.trial_list)} trials done",
                 font=("Segoe UI", 26), bg="#0a0a14", fg="#ffffff").pack(pady=4)

        def cont():
            overlay.destroy()
            now = time.time()
            self.current_phase = "rest"
            self.phase_start = now
            self.phase_end = now + 1.0
            self.stim_window.after(50, self._update_loop)

        StyledButton(overlay, "▶  Continue", cont, bg="#006644", hover="#00aa66",
                     font=("Segoe UI", 16, "bold"), padx=34, pady=16).pack(pady=30)

    # ==================================================================
    # SCREEN 3: Complete
    # ==================================================================
    def _end_session(self, cancelled=False):
        if not cancelled:
            play_sound("end")
        if self.stim_window is not None:
            try:
                self.stim_window.destroy()
            except Exception:
                pass
            self.stim_window = None

        # A finished run is always saved. A stopped / emergency-stopped run lets
        # the user choose to save the partial data or discard it.
        save = True
        if cancelled:
            save = messagebox.askyesno(
                "Save recording?",
                "The recording was stopped early.\n\n"
                "Save the markers collected so far?")
        csv_path = summary_path = None
        if save:
            try:
                csv_path, summary_path = self._save_outputs()
            except Exception as e:
                messagebox.showerror("Save error", str(e))
        # Never exit here — always go back into the app (complete -> main menu).
        self._swap(lambda p: self._build_complete(p, cancelled, save, csv_path, summary_path))

    def _build_complete(self, parent, cancelled, saved, csv_path, summary_path):
        frame = tk.Frame(parent, bg=BG)
        c = self.cfg
        tk.Label(frame, text="Recording Stopped" if cancelled else "Recording Complete",
                 font=("Segoe UI", 26, "bold"), bg=BG,
                 fg=WARN if cancelled else OK).pack(pady=(24, 4))

        # Recording number + date/time line
        tk.Label(frame,
                 text=f"Recording R{c.get('run', 1):02d}   ·   "
                      f"{datetime.now():%Y-%m-%d  %H:%M:%S}   ·   "
                      f"{c['subject_id']}  ({c['mode'].upper()})",
                 font=("Segoe UI", 12), bg=BG, fg="#aaa").pack(pady=(0, 4))
        tk.Label(frame, text="Saved to ./recordings/" if saved else "Not saved (discarded)",
                 font=("Segoe UI", 12, "bold"), bg=BG,
                 fg=OK if saved else WARN).pack(pady=(0, 10))

        cols = ("class", "trials", "accepted", "rejected")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        for col, wdt in zip(cols, (240, 90, 100, 100)):
            tree.heading(col, text=col.capitalize())
            tree.column(col, width=wdt, anchor="center")
        for key, r in self.results.items():
            tree.insert("", "end", values=(CLASS_INFO[key]["title"],
                                           r["trials"], r["accepted"], r["rejected"]))
        tree.pack(padx=40, pady=10)

        for p in (csv_path, summary_path):
            if p:
                tk.Label(frame, text=f"Saved: {p}", font=("Consolas", 10),
                         bg=BG, fg="#8fc").pack()

        btns = tk.Frame(frame, bg=BG)
        btns.pack(pady=22)
        StyledButton(btns, "⟵  Back to Main Menu", self.show_setup,
                     bg="#006644", hover="#00aa66",
                     font=("Segoe UI", 13, "bold"), padx=24, pady=12).pack(side="left", padx=6)
        StyledButton(btns, "✕  Exit", self.quit_app,
                     bg="#552222", hover="#aa3333").pack(side="left", padx=6)
        return frame

    # ==================================================================
    # Output files
    # ==================================================================
    def _file_stem(self, ts):
        """Detailed, unique stem: subject_class_mode_R##_YYYYMMDD_HHMMSS."""
        c = self.cfg
        if c["mode"] == "train":
            return f"{c['subject_id']}_{c['train_class']}_train_R{c['run']:02d}_{ts}"
        return f"{c['subject_id']}_MIX_test_R{c['run']:02d}_{ts}"

    def _save_outputs(self):
        c = self.cfg
        p = Path("recordings")
        p.mkdir(exist_ok=True)
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S")     # goes into the filename
        stem = self._file_stem(ts)
        csv_path = p / f"{stem}_markers.csv"
        summary_path = p / f"{stem}_summary.txt"

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time_sec", "marker_id", "signal_name",
                        "trial_num", "accepted", "duration_sec"])
            for m in self.markers:
                w.writerow([m["time_sec"], m["marker_id"], m["signal_name"],
                            m["trial_num"], m["accepted"], m["duration_sec"]])

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("EEG Recording Summary\n")
            f.write("=" * 50 + "\n")
            f.write(f"Subject ID    : {c['subject_id']}\n")
            f.write(f"Mode          : {c['mode'].upper()}\n")
            f.write(f"Recording #   : R{c['run']:02d}\n")
            f.write(f"Date          : {now.strftime('%Y-%m-%d')}\n")
            f.write(f"Time          : {now.strftime('%H:%M:%S')}\n")
            if c["mode"] == "train":
                f.write(f"Class         : {c['train_class']} "
                        f"(marker {CLASS_INFO[c['train_class']]['marker_id']})\n")
            f.write(f"Timing        : Cue={c['cue_dur']}s  Action={c['active_dur']}s  "
                    f"Rest={c['rest_dur']}s\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"{'Class':<22}{'Trials':>8}{'Accepted':>10}{'Rejected':>10}\n")
            f.write("-" * 50 + "\n")
            for key, r in self.results.items():
                f.write(f"{key:<22}{r['trials']:>8}{r['accepted']:>10}{r['rejected']:>10}\n")
            tot = sum(r["trials"] for r in self.results.values())
            acc = sum(r["accepted"] for r in self.results.values())
            rej = sum(r["rejected"] for r in self.results.values())
            f.write("-" * 50 + "\n")
            f.write(f"{'TOTAL':<22}{tot:>8}{acc:>10}{rej:>10}\n")
        return str(csv_path), str(summary_path)

    def _auto_run_number(self):
        """Next run number for this subject + mode (+ class for train)."""
        c = self.cfg
        sid = self.fields["subject_id"].get().strip() if getattr(self, "fields", None) else c["subject_id"]
        sid = sid or "S001"
        if c["mode"] == "train":
            prefix = f"{sid}_{c['train_class']}_train_R"
        else:
            prefix = f"{sid}_MIX_test_R"
        max_r = 0
        for fp in glob.glob(str(Path("recordings") / f"{prefix}*_markers.csv")):
            mt = re.search(r"_R(\d+)_markers\.csv$", fp)
            if mt:
                max_r = max(max_r, int(mt.group(1)))
        self.cfg["run"] = max_r + 1

    def quit_app(self):
        if self.stim_window is not None:
            try:
                self.stim_window.destroy()
            except Exception:
                pass
        self.destroy()


def main():
    Path("recordings").mkdir(exist_ok=True)
    EEGApp().mainloop()


if __name__ == "__main__":
    main()
