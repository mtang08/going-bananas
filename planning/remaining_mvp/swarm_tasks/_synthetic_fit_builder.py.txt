"""Deterministic synthetic FIT activity for decoder tests. Contains no real athlete data."""
from __future__ import annotations

import io
import struct
import zipfile

FIT_EPOCH_OFFSET = 631065600
START_FIT_TS = 1163246400  # 2026-11-10T12:00:00Z
LAT_CANARY = 123456789
_CRC = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)
_FMT = {0x00: "B", 0x02: "B", 0x84: "H", 0x85: "i", 0x86: "I"}


def crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC[byte & 0xF]
        tmp = _CRC[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC[(byte >> 4) & 0xF]
    return crc


class _Writer:
    def __init__(self) -> None:
        self.body = bytearray()
        self.defs: dict[int, list[tuple[int, int, int]]] = {}

    def define(self, local: int, global_num: int, fields: list[tuple[int, int, int]]) -> None:
        self.defs[local] = fields
        self.body += struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
        for num, size, base in fields:
            self.body += struct.pack("<BBB", num, size, base)

    def data(self, local: int, *values: object) -> None:
        self.body += struct.pack("<B", local)
        for (_, size, base), value in zip(self.defs[local], values, strict=True):
            if base == 0x07:
                assert isinstance(value, str)
                self.body += value.encode().ljust(size, b"\x00")[:size]
            else:
                self.body += struct.pack("<" + _FMT[base], value)

    def finish(self) -> bytes:
        header = struct.pack("<BBHI4s", 14, 0x20, 21221, len(self.body), b".FIT")
        header += struct.pack("<H", crc16(header))
        payload = header + bytes(self.body)
        return payload + struct.pack("<H", crc16(payload))


def build_synthetic_fit() -> bytes:
    w = _Writer()
    t0 = START_FIT_TS
    w.define(0, 0, [(0, 1, 0x00), (1, 2, 0x84), (2, 2, 0x84), (4, 4, 0x86)])
    w.data(0, 4, 1, 4315, t0)
    w.define(1, 21, [(253, 4, 0x86), (0, 1, 0x00), (1, 1, 0x00)])
    w.data(1, t0, 0, 0)
    w.define(2, 20, [(253, 4, 0x86), (0, 4, 0x85), (3, 1, 0x02), (4, 1, 0x02),
                     (5, 4, 0x86), (73, 4, 0x86), (78, 4, 0x86)])
    for t in [*range(0, 300), *range(312, 600)]:
        w.data(2, t0 + t, LAT_CANARY, 120 + t // 60, 85, t * 300, 3000, (10 + 500) * 5)
        if t == 299:
            w.data(1, t0 + 300, 0, 4)
            w.data(1, t0 + 312, 0, 0)
    w.data(1, t0 + 600, 0, 4)
    w.define(3, 19, [(254, 2, 0x84), (253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86),
                     (9, 4, 0x86), (15, 1, 0x02), (16, 1, 0x02), (24, 1, 0x00), (110, 4, 0x86), (71, 2, 0x84)])
    w.data(3, 0, t0 + 300, t0, 300000, 300000, 90000, 122, 125, 0, 3000, 0)
    w.data(3, 1, t0 + 600, t0 + 312, 288000, 288000, 86400, 127, 129, 7, 3000, 1)
    w.define(4, 18, [(253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86), (9, 4, 0x86),
                     (5, 1, 0x00), (6, 1, 0x00), (192, 1, 0x02), (193, 1, 0x02)])
    w.data(4, t0 + 600, t0, 600000, 588000, 176400, 1, 0, 75, 65)
    w.define(5, 27, [(254, 2, 0x84), (0, 16, 0x07), (1, 1, 0x00), (2, 4, 0x86), (3, 1, 0x00),
                     (5, 4, 0x86), (6, 4, 0x86), (7, 1, 0x00)])
    w.data(5, 0, "Warm up", 0, 300000, 2, 0, 0, 2)
    w.data(5, 1, "Run", 1, 80000, 0, 3200, 3600, 0)
    w.define(6, 27, [(254, 2, 0x84), (1, 1, 0x00), (2, 4, 0x86), (4, 4, 0x86)])
    w.data(6, 2, 6, 1, 4)
    w.data(5, 3, "Cool down", 5, 0, 1, 230, 245, 3)
    return w.finish()


def build_synthetic_zip(members: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in (members or {"99000001_ACTIVITY.fit": build_synthetic_fit()}).items():
            archive.writestr(name, data)
    return buffer.getvalue()
