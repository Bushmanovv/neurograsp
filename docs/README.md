# docs

## The report

**[`ENCS5300-Final-Report.pdf`](ENCS5300-Final-Report.pdf)** — the submitted
graduation report, 14 chapters. Start at Chapter 9 if you only read one: it
documents the evaluation methodology audit that reshaped the project, and
Chapter 10 has the final per-class results.

| Ch | | Ch | |
|---|---|---|---|
| 1 | Introduction | 8 | Feature Extraction |
| 2 | Related Work | 9 | Classification & Training |
| 3 | Medical & Physiological Foundations | 10 | Results & Analysis |
| 4 | System Overview & Hardware | 11 | Configuration & Control Application |
| 5 | Methodology | 12 | Real-Time Inference |
| 6 | Data Collection | 13 | Discussion |
| 7 | Signal Processing Pipeline | 14 | Conclusion |

[`report/`](report/) is the LaTeX source. It builds with a standard TeX Live:

```bash
cd report && pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```

Figures are in `report/Assets/`. `main.tex` `\input`s each chapter by bare name.

## Other documents

| | |
|---|---|
| [`diagrams/`](diagrams/) | System architecture, control flow, wiring, power distribution, the label→action mapping, and the 24-part exploded parts table |
| [`eeg-bci-research-notes.md`](eeg-bci-research-notes.md) | Background research notes on EEG artifact-based control |
| [`inmoov-build-guide.md`](inmoov-build-guide.md) | Mechanical build notes for the hand |
| [`ENCS5300-Similarity-Report.pdf`](ENCS5300-Similarity-Report.pdf) | The submission's originality-check output |
| [`archive/`](archive/) | Superseded early drafts — kept for provenance, **not accurate about the built system** |

## A note on the diagrams

`diagrams/system-architecture.png` and `diagrams/wiring-diagram.png` show servos
driven through a **PCA9685** I²C expander. The shipped firmware does not use one —
it drives all six servos directly from ESP32 GPIO pins via ESP32Servo, which
removed a board and a failure mode. The rest of each diagram is accurate.
[`../hand-firmware/include/config.h`](../hand-firmware/include/config.h) is the
authority on pins and wiring.

`archive/` has the same caveat several times over: it contains the layer-plan
drafts written before the firmware was built, including a build plan whose later
layers are marked "not started" and which were in fact completed. The current
descriptions live in each component's own README.
