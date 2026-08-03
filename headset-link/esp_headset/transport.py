"""Swappable link between the virtual headset and the classifier.

Everything above this module sees only ``Transport``: a reliable, ordered byte
stream. TCP works today; RFCOMM/SPP is the same socket API on Linux, so the
Bluetooth swap touches nothing but the two factory functions at the bottom.

BLE is a packet transport rather than a stream, so it gets its own adapter that
reassembles GATT notifications into the stream this interface promises.
"""

from __future__ import annotations

import socket
from abc import ABC, abstractmethod


class Transport(ABC):
    """A reliable, ordered byte stream."""

    @abstractmethod
    def send(self, data: bytes) -> None: ...

    @abstractmethod
    def recv_exactly(self, n: int) -> bytes:
        """Read exactly ``n`` bytes, or raise ``ConnectionError`` if the peer hangs up."""

    def set_timeout(self, seconds: float | None) -> None:
        """Optional: transports that can't set one may ignore this."""

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class SocketTransport(Transport):
    """Shared implementation for any SOCK_STREAM socket (TCP, RFCOMM)."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def recv_exactly(self, n: int) -> bytes:
        chunks, remaining = [], n
        while remaining:
            chunk = self.sock.recv(min(remaining, 65536))
            if not chunk:
                raise ConnectionError(f"peer closed after {n - remaining}/{n} bytes")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def set_timeout(self, seconds: float | None) -> None:
        """Extend the deadline, e.g. while waiting for the classifier's reply."""
        self.sock.settimeout(seconds)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# TCP (phase 1: ESP32 over WiFi)
# --------------------------------------------------------------------------- #
def tcp_connect(host: str, port: int, timeout: float = 10.0) -> Transport:
    """Headset side: dial the classifier."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return SocketTransport(sock)


def tcp_listen(port: int, host: str = "0.0.0.0", timeout: float | None = None) -> Transport:
    """Classifier side: accept one headset connection, then stop listening."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    srv.settimeout(timeout)
    try:
        conn, _ = srv.accept()
    finally:
        srv.close()
    conn.settimeout(timeout)
    return SocketTransport(conn)


# --------------------------------------------------------------------------- #
# Bluetooth (phase 2)
# --------------------------------------------------------------------------- #
def rfcomm_listen(channel: int = 1, timeout: float | None = None) -> Transport:
    """Classifier side: accept an SPP connection from the ESP32 (Linux only).

    RFCOMM is a stream socket, so ``SocketTransport`` covers it unchanged. The
    Pi must advertise an SPP service record first::

        sudo sdptool add --channel=1 SP
        sudo hciconfig hci0 piscan

    Not available on macOS: CPython exposes ``AF_BLUETOOTH`` only on Linux.
    """
    if not hasattr(socket, "AF_BLUETOOTH"):
        raise NotImplementedError(
            "AF_BLUETOOTH sockets are Linux-only; run this on the Pi, or use "
            "tcp_listen() during development.")
    srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((socket.BDADDR_ANY, channel))
    srv.listen(1)
    srv.settimeout(timeout)
    try:
        conn, _ = srv.accept()
    finally:
        srv.close()
    conn.settimeout(timeout)
    return SocketTransport(conn)


def ble_connect(*_args, **_kwargs) -> Transport:
    """BLE GATT adapter -- not implemented.

    Needed only if the headset is an ESP32-S3/C3 (no Bluetooth Classic). Wrap
    ``bleak`` and reassemble notifications into a stream: negotiate MTU 247 and
    a 7.5-15 ms connection interval, or throughput falls below the 7.6 kB/s the
    stream needs.
    """
    raise NotImplementedError(
        "BLE transport not implemented; classic ESP32 has SPP -- use rfcomm_listen().")
