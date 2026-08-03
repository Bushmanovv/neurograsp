"""Labels-CSV parsing: column auto-detection, units, and manual overrides."""

import pytest

from virtual_headset import read_labels


def write_csv(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text.strip() + "\n")
    return p


# --------------------------------------------------------------------------- #
# Auto-detected columns
# --------------------------------------------------------------------------- #
def test_auto_detects_onset_duration_label(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", """
onset,duration,label
1.0,0.5,blink
2.5,0.25,jaw_clench
""")
    labels = read_labels(csv)

    assert [l.onset for l in labels] == [1.0, 2.5]
    assert [l.duration for l in labels] == [0.5, 0.25]
    assert [l.description for l in labels] == ["blink", "jaw_clench"]


def test_auto_detects_alternate_names_and_derives_duration_from_end(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", """
start_time,end_time,side
1.0,1.75,left
4.0,4.50,right
""")
    labels = read_labels(csv)

    assert [l.onset for l in labels] == [1.0, 4.0]
    assert [l.duration for l in labels] == pytest.approx([0.75, 0.5])
    assert [l.description for l in labels] == ["left", "right"]


def test_missing_duration_and_end_gives_zero_duration(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", """
time,event
3.0,bruxism
""")
    labels = read_labels(csv)
    assert labels[0].duration == 0.0
    assert labels[0].description == "bruxism"


def test_rows_are_sorted_by_onset_and_blank_rows_skipped(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", """
onset,label
5.0,second
,orphan
1.0,first
""")
    labels = read_labels(csv)
    assert [l.description for l in labels] == ["first", "second"]


# --------------------------------------------------------------------------- #
# ms units + manual overrides
# --------------------------------------------------------------------------- #
def test_ms_file_with_manual_overrides(tmp_path):
    # Neither column is auto-detectable, and times are in milliseconds.
    csv = write_csv(tmp_path, "labels.csv", """
t_ms,evt
1500,blink
2750,blink
""")
    with pytest.raises(ValueError, match="auto-detect an onset/time column"):
        read_labels(csv)

    labels = read_labels(csv, time_unit="ms", time_col="t_ms", label_col="evt")

    assert [l.onset for l in labels] == pytest.approx([1.5, 2.75])
    assert [l.description for l in labels] == ["blink", "blink"]


def test_ms_scaling_applies_to_duration_too(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", """
onset,duration,label
1500,500,blink
""")
    labels = read_labels(csv, time_unit="ms")
    assert labels[0].onset == pytest.approx(1.5)
    assert labels[0].duration == pytest.approx(0.5)


def test_ms_scaling_applies_to_derived_end_duration(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", """
onset,end,label
1000,1750,blink
""")
    labels = read_labels(csv, time_unit="ms")
    assert labels[0].onset == pytest.approx(1.0)
    assert labels[0].duration == pytest.approx(0.75)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
def test_unknown_override_column_raises(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", "onset,label\n1.0,blink")
    with pytest.raises(ValueError, match="--time-col='nope'"):
        read_labels(csv, time_col="nope")


def test_undetectable_label_column_raises(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", "onset,whatever\n1.0,blink")
    with pytest.raises(ValueError, match="auto-detect a label/event column"):
        read_labels(csv)


def test_bad_time_unit_raises(tmp_path):
    csv = write_csv(tmp_path, "labels.csv", "onset,label\n1.0,blink")
    with pytest.raises(ValueError, match="time_unit"):
        read_labels(csv, time_unit="us")
