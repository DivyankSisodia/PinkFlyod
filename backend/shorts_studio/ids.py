"""Prefixed, time-sortable IDs (ULID layout: 48-bit milliseconds + 80 random bits, Crockford base32)."""
from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = ("prj", "src", "seg", "scn", "tk", "ovl", "sfx", "gpc", "job", "rnd")


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        out.append(_ALPHABET[rem])
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix {prefix!r}")
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    return f"{prefix}_{_encode(ms, 10)}{_encode(secrets.randbits(80), 16)}"
