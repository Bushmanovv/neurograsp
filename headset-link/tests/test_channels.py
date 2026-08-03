"""Channel-name normalization: the fiddly part, tested on in-memory lists."""

import pytest

from virtual_headset import (
    ALL_CH,
    CANONICAL,
    normalize_channel,
    resolve_montage,
)

# A source montage in "modern" clinical export form: EEG/POL prefixes, -REF
# suffixes, 10-10 temporal names, plus non-EEG trailers.
MODERN_SOURCE = [
    "EEG Fp1-REF", "EEG Fp2-REF", "EEG Fz-REF", "EEG F8-REF", "EEG F7-REF",
    "EEG F4-REF", "EEG F3-REF", "EEG C4-REF", "EEG C3-REF", "EEG O2-REF",
    "EEG P3-REF", "EEG Cz-REF", "EEG O1-REF", "EEG P4-REF", "EEG Pz-REF",
    "EEG P8-REF", "EEG P7-REF", "EEG T8-REF", "EEG T7-REF",
    "EKG", "Status",
]


# --------------------------------------------------------------------------- #
# "EEG X-REF" prefix / reference-suffix handling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "source,expected",
    [
        ("EEG Fp1-REF", "Fp1"),
        ("POL C3-REF", "C3"),
        ("EEG Fz", "Fz"),
        ("Fp2-LE", "Fp2"),
        ("EEG O1_REF", "O1"),      # underscore separator
        ("EEG P4 REF", "P4"),      # space separator
        ("eeg fp1-ref", "Fp1"),    # case-insensitive prefix, canonical casing out
        ("  Pz-Ref  ", "Pz"),      # surrounding whitespace
        ("Fp1-A1", "Fp1"),         # ear reference
    ],
)
def test_prefix_and_reference_suffix(source, expected):
    assert normalize_channel(source) == expected


# --------------------------------------------------------------------------- #
# Modern 10-10 -> old 10-20 remap
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "source,expected",
    [
        ("T7", "T3"),
        ("T8", "T4"),
        ("P7", "T5"),
        ("P8", "T6"),
        ("EEG T7-REF", "T3"),
        ("POL P8-LE", "T6"),
    ],
)
def test_modern_to_old_remap(source, expected):
    assert normalize_channel(source) == expected


def test_old_names_pass_through_unchanged():
    for name in ("T3", "T4", "T5", "T6"):
        assert normalize_channel(name) == name


# --------------------------------------------------------------------------- #
# CRITICAL: Cz is a real channel, not a reference marker.
# A stripper that deleted reference tokens anywhere in the name would eat it,
# because Cz is itself a common reference (e.g. "Fp1-Cz").
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "source", ["Cz", "CZ", "cz", "EEG Cz-REF", "Cz-LE", "POL Cz-Ref", "EEG CZ_REF"]
)
def test_cz_is_never_eaten(source):
    assert normalize_channel(source) == "Cz"


def test_cz_as_a_reference_suffix_is_dropped_but_channel_kept():
    # Here Cz is the *reference*, so the channel is Fp1 ...
    assert normalize_channel("Fp1-Cz") == "Fp1"
    # ... and the real Cz channel still normalizes to Cz.
    assert normalize_channel("Cz-Cz") == "Cz"


def test_cz_survives_a_full_montage_resolution():
    res = resolve_montage(MODERN_SOURCE)
    assert "Cz-Ref" in res.mapping.values()
    assert "Cz-Ref" not in res.missing
    assert res.ok


# --------------------------------------------------------------------------- #
# Non-EEG channels are ignored
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("source", ["EKG", "ECG", "Status", "A1", "A2", "", "   ", None])
def test_non_eeg_is_ignored(source):
    assert normalize_channel(source) is None


# --------------------------------------------------------------------------- #
# Whole-montage resolution
# --------------------------------------------------------------------------- #
def test_full_modern_montage_maps_to_all_19_in_order():
    res = resolve_montage(MODERN_SOURCE)

    assert res.ok
    assert res.found == 19
    assert res.missing == []
    assert res.ignored == ["EKG", "Status"]
    # Every canonical name is produced exactly once.
    assert sorted(res.mapping.values()) == sorted(ALL_CH)
    # The 10-10 names were remapped to the 10-20 names config expects.
    assert res.mapping["EEG T7-REF"] == "T3-Ref"
    assert res.mapping["EEG P8-REF"] == "T6-Ref"


def test_already_canonical_montage_needs_no_renames():
    res = resolve_montage(ALL_CH)
    assert res.ok
    assert res.renamed == []
    assert res.mapping == {name: name for name in ALL_CH}


def test_missing_channel_is_reported_exactly():
    source = [c for c in MODERN_SOURCE if "Cz" not in c]
    res = resolve_montage(source)

    assert not res.ok
    assert res.found == 18
    assert res.missing == ["Cz-Ref"]


def test_several_missing_channels_listed_in_canonical_order():
    source = [c for c in MODERN_SOURCE if not any(k in c for k in ("Fp2", "O1", "T7"))]
    res = resolve_montage(source)

    assert res.found == 16
    assert res.missing == ["Fp2-Ref", "O1-Ref", "T3-Ref"]


def test_duplicate_electrodes_are_dropped_not_double_mapped():
    res = resolve_montage(MODERN_SOURCE + ["EEG Fp1-LE"])
    assert res.ok
    assert res.duplicates == [("EEG Fp1-LE", "Fp1")]
    assert list(res.mapping.values()).count("Fp1-Ref") == 1


def test_bare_naming_mode_writes_electrode_names():
    res = resolve_montage(MODERN_SOURCE, naming="bare")
    assert res.ok
    assert sorted(res.mapping.values()) == sorted(CANONICAL)
    assert res.mapping["EEG Cz-REF"] == "Cz"


def test_canonical_order_matches_config_all_ch():
    assert CANONICAL == [c.split("-")[0] for c in ALL_CH]
    assert CANONICAL[0] == "Fp1" and CANONICAL[-1] == "T3"
    assert len(ALL_CH) == 19
