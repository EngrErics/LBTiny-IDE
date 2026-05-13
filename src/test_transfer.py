#!/usr/bin/env python3
"""
test_transfer.py
================

Step 3 verification: exercise the LBTiny Supervisor's receive protocol from
the host side, before any GUI work begins.

Sends a payload to the Nucleo over the ST-Link VCP and verifies that the
returned CRC matches a locally-computed CRC over the same data.

Protocol:
    PC  -> Nucleo:  0xA5  [len_le_4B]  [payload]
    Nucleo -> PC :  0x5A  [recv_len_le_4B]  [crc_le_4B]

Built-in test modes:
    --self                 small built-in vectors, no file needed
    --file PATH            load PATH and transfer it
    --random N             generate N random bytes and transfer
    --overflow             send 5000 bytes (exceeds 4096 buffer) to test
                           overflow reporting
    --empty                send a zero-length payload

Usage examples:
    python test_transfer.py --port /dev/ttyACM0 --self
    python test_transfer.py --port /dev/ttyACM0 --random 3000
    python test_transfer.py --port /dev/ttyACM0 --file program.bin
    python test_transfer.py --port /dev/ttyACM0 --overflow
"""

import argparse
import os
import struct
import sys
import time

import serial  # pyserial

from stm32_crc import stm32_crc32, padded_length

SYNC_HOST_TO_NUCLEO = 0xA5
SYNC_NUCLEO_TO_HOST = 0x5A
RESPONSE_SIZE = 9   # 1 sync + 4 len + 4 crc
MAX_PAYLOAD = 4096


def send_and_verify(port: serial.Serial, payload: bytes, verbose: bool = True) -> bool:
    """
    Send `payload` to the Nucleo and verify the returned CRC matches a
    locally-computed CRC. Returns True on PASS, False on FAIL.

    Note: the locally-computed CRC is over `payload[:MAX_PAYLOAD]` because
    that's what the Nucleo can actually store. If we send more than MAX,
    the Nucleo will compute over the first MAX bytes only.
    """
    declared_len = len(payload)

    # Drain any leftover bytes from the boot banner or previous transfers
    # so we don't accidentally read them as response data.
    drained = port.read(port.in_waiting or 0)
    if drained and verbose:
        print(f"  [info] drained {len(drained)} stale bytes from RX buffer "
              f"before transfer")

    # Build and send the request
    header = bytes([SYNC_HOST_TO_NUCLEO]) + struct.pack("<I", declared_len)
    t_start = time.time()
    port.write(header + payload)   # single write - no gap between header and payload
    port.flush()

    # The Nucleo will respond with exactly 9 bytes once it finishes.
    # Set a generous read timeout so a slow transfer doesn't time out
    # before completion. Max payload at 115200 is ~360 ms, plus a margin.
    port.timeout = 5.0
    resp = port.read(RESPONSE_SIZE)
    t_end = time.time()

    print(f"  declared_len:  {declared_len} bytes "
          f"(padded for CRC: {padded_length(payload[:MAX_PAYLOAD])} bytes)")
    print(f"  elapsed:       {t_end - t_start:.3f} s")
    print(f"  response_raw:  {resp.hex(' ') if resp else '(no response)'}")

    if len(resp) != RESPONSE_SIZE:
        print(f"  FAIL: expected {RESPONSE_SIZE} bytes in response, got {len(resp)}")
        return False

    if resp[0] != SYNC_NUCLEO_TO_HOST:
        print(f"  FAIL: bad response sync byte 0x{resp[0]:02X}, "
              f"expected 0x{SYNC_NUCLEO_TO_HOST:02X}")
        return False

    recv_len, recv_crc = struct.unpack("<II", resp[1:9])

    # Local CRC is over what the Nucleo would have stored (up to MAX_PAYLOAD)
    stored_payload = payload[:MAX_PAYLOAD]
    local_crc = stm32_crc32(stored_payload)

    print(f"  nucleo_recv_len: {recv_len}  (host declared: {declared_len})")
    print(f"  nucleo_crc:      0x{recv_crc:08X}")
    print(f"  local_crc:       0x{local_crc:08X}  "
          f"(over first {len(stored_payload)} bytes)")

    # Diagnostic interpretation
    overflow = declared_len > MAX_PAYLOAD

    if recv_len != declared_len:
        print(f"  FAIL: length mismatch - host said {declared_len}, "
              f"Nucleo echoed {recv_len}. Bytes were dropped or framing lost.")
        return False

    if recv_crc != local_crc:
        if overflow:
            print(f"  FAIL: CRCs disagree even after accounting for overflow truncation.")
        else:
            print(f"  FAIL: CRC mismatch - data corrupted during transfer.")
        return False

    if overflow:
        print(f"  PASS (overflow case: host sent {declared_len}, "
              f"Nucleo stored {MAX_PAYLOAD}, CRCs agree on stored portion)")
    else:
        print(f"  PASS")
    return True


def main():
    ap = argparse.ArgumentParser(description="Test LBTiny supervisor receive protocol")
    ap.add_argument("--port", default="/dev/ttyACM0", help="Serial port (default: /dev/ttyACM0)")
    ap.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    ap.add_argument("--self", action="store_true", help="Run built-in test vectors")
    ap.add_argument("--file", help="Send a binary file")
    ap.add_argument("--random", type=int, metavar="N", help="Send N random bytes")
    ap.add_argument("--overflow", action="store_true", help="Send 5000 bytes (>4096 buffer)")
    ap.add_argument("--empty", action="store_true", help="Send a zero-length payload")
    args = ap.parse_args()

    if not any([args.self, args.file, args.random, args.overflow, args.empty]):
        ap.error("Pick at least one of: --self, --file, --random N, --overflow, --empty")

    print(f"Opening {args.port} at {args.baud} baud...")
    try:
        port = serial.Serial(args.port, args.baud, timeout=2.0)
    except serial.SerialException as e:
        print(f"Could not open port: {e}", file=sys.stderr)
        return 1

    # Give the Nucleo a moment to finish booting if we just opened the port
    time.sleep(0.5)

    test_cases = []

    if args.self:
        test_cases.extend([
            ("empty",                b""),
            ("single byte 0x00",     bytes([0x00])),
            ("'ABCD'",               b"ABCD"),
            ("'12345678'",           b"12345678"),
            ("64-byte counting",     bytes(range(64))),
            ("1024-byte 0xAA fill",  bytes([0xAA]) * 1024),
            ("4096-byte exact-fit",  bytes([(i & 0xFF) for i in range(4096)])),
        ])

    if args.empty:
        test_cases.append(("explicit empty", b""))

    if args.random is not None:
        import random
        random.seed(0xC0FFEE)
        payload = bytes(random.randint(0, 255) for _ in range(args.random))
        test_cases.append((f"random {args.random} bytes", payload))

    if args.overflow:
        # Use a recognizable pattern so we know which bytes survived
        payload = bytes([(i & 0xFF) for i in range(5000)])
        test_cases.append(("5000-byte overflow", payload))

    if args.file:
        with open(args.file, "rb") as f:
            payload = f.read()
        test_cases.append((f"file: {os.path.basename(args.file)}", payload))

    total = len(test_cases)
    passes = 0

    print("=" * 60)
    for i, (label, payload) in enumerate(test_cases, start=1):
        print(f"\n[{i}/{total}] {label}")
        print("-" * 60)
        if send_and_verify(port, payload):
            passes += 1
        # Small inter-test gap so the Nucleo's [xfer] diagnostic line lands
        # cleanly and the RX buffer settles before the next round.
        time.sleep(0.30)

    print("\n" + "=" * 60)
    print(f"Summary: {passes}/{total} passed")
    port.close()
    return 0 if passes == total else 2


if __name__ == "__main__":
    sys.exit(main())