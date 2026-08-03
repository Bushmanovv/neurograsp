"""The frame the sender writes and pi_receive.py reads, and the verdict it sends back."""

import json
import struct

import pytest

from pi_receive import (HEADER_SIZE, MAGIC, RESULT_HEADER_SIZE, RESULT_MAGIC,
                        build_header, build_result, parse_header, parse_result_header)


def test_header_is_nine_bytes_and_round_trips():
    buf = build_header(3, 43406)
    assert len(buf) == 9 == HEADER_SIZE
    assert buf[:4] == b"EDF1" == MAGIC
    assert parse_header(buf) == (3, 43406)


def test_length_is_little_endian():
    # The firmware writes the length byte by byte, LSB first. Pin that.
    assert build_header(0, 0x01020304)[5:9] == bytes([0x04, 0x03, 0x02, 0x01])


def test_two_frames_concatenate_without_a_delimiter():
    # This is why the length prefix exists: RFCOMM is a stream, and one open
    # link carries many button presses back to back.
    a, b = b"AAAA", b"BBBBBB"
    wire = build_header(1, len(a)) + a + build_header(4, len(b)) + b

    cid, n = parse_header(wire)
    assert (cid, n) == (1, 4)
    rest = wire[HEADER_SIZE + n:]
    assert wire[HEADER_SIZE:HEADER_SIZE + n] == a

    cid2, n2 = parse_header(rest)
    assert (cid2, n2) == (4, 6)
    assert rest[HEADER_SIZE:HEADER_SIZE + n2] == b


def test_bad_magic_rejected():
    buf = bytearray(build_header(0, 10))
    buf[:4] = b"XXXX"
    with pytest.raises(ValueError, match="bad magic"):
        parse_header(bytes(buf))


def test_short_header_rejected():
    with pytest.raises(ValueError, match="header needs 9 bytes"):
        parse_header(b"EDF1")


@pytest.mark.parametrize("length", [0, 9 << 20])
def test_implausible_length_rejected(length):
    buf = struct.pack("<4sBI", MAGIC, 0, length)
    with pytest.raises(ValueError, match="implausible snippet length"):
        parse_header(buf)


# --------------------------------------------------------------------------- #
# The reply: what the Pi's classifier said, coming back to the dashboard
# --------------------------------------------------------------------------- #
def test_result_round_trips():
    verdict = {"class_id": 2, "returncode": 0, "seconds": 0.7, "output": "confirmed C\n"}
    wire = build_result(verdict)

    assert wire[:4] == b"RES1" == RESULT_MAGIC
    n = parse_result_header(wire)
    assert n == len(wire) - RESULT_HEADER_SIZE
    assert json.loads(wire[RESULT_HEADER_SIZE:RESULT_HEADER_SIZE + n]) == verdict


def test_result_is_framed_so_a_stream_can_find_its_end():
    # Same reason the snippet has a length prefix: the reply shares one open link
    # with every later button press, and JSON has no terminator.
    a = build_result({"class_id": 0, "output": "a"})
    b = build_result({"class_id": 1, "output": "b"})
    wire = a + b

    n = parse_result_header(wire)
    assert json.loads(wire[RESULT_HEADER_SIZE:RESULT_HEADER_SIZE + n])["class_id"] == 0
    rest = wire[RESULT_HEADER_SIZE + n:]
    n2 = parse_result_header(rest)
    assert json.loads(rest[RESULT_HEADER_SIZE:RESULT_HEADER_SIZE + n2])["class_id"] == 1


def test_non_ascii_output_survives_the_wire():
    # The length is in *bytes*, not characters. A model printing "µV" would
    # truncate the JSON if the header counted characters.
    wire = build_result({"output": "peak 346 µV — ok"})
    n = parse_result_header(wire)
    body = wire[RESULT_HEADER_SIZE:]
    assert len(body) == n
    assert json.loads(body)["output"] == "peak 346 µV — ok"


def test_bad_result_magic_rejected():
    buf = bytearray(build_result({"ok": True}))
    buf[:4] = b"EDF1"                      # a snippet header is not a verdict
    with pytest.raises(ValueError, match="bad result magic"):
        parse_result_header(bytes(buf))
