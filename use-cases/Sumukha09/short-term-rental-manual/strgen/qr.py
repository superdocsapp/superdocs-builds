"""Pure-standard-library QR code encoder (byte mode, versions 1-10).

No dependencies. Implements ISO/IEC 18004 essentials:
Reed-Solomon ECC over GF(256), byte-mode segmentation, interleaving,
function patterns, format/version info, all 8 masks with penalty scoring,
plus ``verify_matrix`` — a structural decoder used by the test-suite to prove
every generated symbol round-trips (BCH-valid format info, RS-consistent
blocks, exact payload recovery).
"""

from __future__ import annotations

import struct
import zlib

__all__ = ["make", "svg", "png_bytes", "wifi_payload", "verify_matrix",
           "QRError"]

MAX_VERSION = 10


class QRError(ValueError):
    pass


# --------------------------------------------------------------------------
# GF(256) arithmetic — irreducible polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11D)
# --------------------------------------------------------------------------

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256

_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gmul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator(nsym: int) -> list[int]:
    """Monic generator polynomial, highest degree first."""
    g = [1]
    for i in range(nsym):
        ng = [0] * (len(g) + 1)
        alpha = _GF_EXP[i]
        for j, coef in enumerate(g):
            ng[j] ^= coef                 # multiply by x
            ng[j + 1] ^= _gmul(coef, alpha)  # multiply by alpha^i
        g = ng
    return g


def _rs_parity(data: list[int], nsym: int) -> list[int]:
    g = _rs_generator(nsym)
    out = list(data) + [0] * nsym
    for i in range(len(data)):
        coef = out[i]
        if coef:
            for j in range(1, nsym + 1):
                out[i + j] ^= _gmul(g[j], coef)
    return out[len(data):]


# --------------------------------------------------------------------------
# Version / layout tables
# --------------------------------------------------------------------------

# version -> ecl -> (total_data_cw, [(blocks, data_cw_per_block), ...], ec_per_block)
_BLOCKS: dict[int, dict[str, tuple]] = {
    1: {"L": (19, [(1, 19)], 7), "M": (16, [(1, 16)], 10),
        "Q": (13, [(1, 13)], 13), "H": (9, [(1, 9)], 17)},
    2: {"L": (34, [(1, 34)], 10), "M": (28, [(1, 28)], 16),
        "Q": (22, [(1, 22)], 26), "H": (16, [(1, 16)], 18)},
    3: {"L": (55, [(1, 55)], 15), "M": (44, [(1, 44)], 26),
        "Q": (34, [(2, 17)], 18), "H": (26, [(2, 13)], 22)},
    4: {"L": (80, [(1, 80)], 20), "M": (64, [(2, 32)], 18),
        "Q": (48, [(2, 24)], 24), "H": (36, [(2, 18)], 28)},
    5: {"L": (108, [(1, 108)], 26), "M": (86, [(2, 43)], 24),
        "Q": (62, [(2, 15), (2, 16)], 28), "H": (46, [(2, 11), (2, 12)], 26)},
    6: {"L": (136, [(2, 68)], 18), "M": (108, [(4, 27)], 16),
        "Q": (76, [(4, 19)], 24), "H": (60, [(4, 15)], 28)},
    7: {"L": (156, [(2, 78)], 20), "M": (124, [(4, 31)], 18),
        "Q": (88, [(2, 14), (4, 15)], 18), "H": (66, [(4, 13), (1, 14)], 26)},
    8: {"L": (194, [(2, 97)], 24), "M": (154, [(2, 38), (2, 39)], 22),
        "Q": (110, [(4, 18), (2, 19)], 22), "H": (86, [(4, 14), (2, 15)], 26)},
    9: {"L": (232, [(2, 116)], 30), "M": (182, [(3, 36), (2, 37)], 22),
        "Q": (128, [(4, 16), (4, 17)], 20), "H": (100, [(4, 12), (4, 13)], 24)},
    10: {"L": (274, [(2, 68), (2, 69)], 18), "M": (216, [(4, 43), (1, 44)], 26),
         "Q": (150, [(6, 15), (2, 16)], 24), "H": (122, [(6, 19), (2, 20)], 28)},
}

_ALIGNMENT: dict[int, list[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
    9: [6, 26, 46], 10: [6, 28, 50],
}

_REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7,
                   7: 0, 8: 0, 9: 0, 10: 0}

_EC_FORMAT_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}


class _Bits:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def push(self, value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def __len__(self) -> int:
        return len(self.bits)


def _encode_segment(payload: bytes, version: int, ecl: str) -> list[int]:
    buf = _Bits()
    buf.push(0b0100, 4)                       # byte mode
    buf.push(len(payload), 16 if version >= 10 else 8)
    for b in payload:
        buf.push(b, 8)

    data_cw = _BLOCKS[version][ecl][0]
    capacity = data_cw * 8
    if len(buf) > capacity:
        raise QRError("payload exceeds capacity")
    # terminator (max 4 bits)
    for _ in range(min(4, capacity - len(buf))):
        buf.bits.append(0)
    # byte alignment
    while len(buf) % 8:
        buf.bits.append(0)
    out: list[int] = []
    for i in range(0, len(buf.bits), 8):
        byte = 0
        for bit in buf.bits[i:i + 8]:
            byte = (byte << 1) | bit
        out.append(byte)
    pad = [0xEC, 0x11]
    while len(out) < data_cw:
        out.append(pad[len(out) % 2])
    return out


def _interleave(version: int, ecl: str, data: list[int]) -> list[int]:
    _, groups, ec_per_block = _BLOCKS[version][ecl]
    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    idx = 0
    for count, size in groups:
        for _ in range(count):
            chunk = data[idx:idx + size]
            idx += size
            data_blocks.append(chunk)
            ec_blocks.append(_rs_parity(chunk, ec_per_block))
    out: list[int] = []
    max_len = max(len(b) for b in data_blocks)
    for i in range(max_len):
        for block in data_blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            out.append(block[i])
    return out


# --------------------------------------------------------------------------
# Matrix construction
# --------------------------------------------------------------------------

def _empty(size: int):
    return [[False] * size for _ in range(size)]


def _function_map(version: int):
    """Return (modules, reserved): modules[r][c]=bool color, reserved[r][c]=True
    for every function-pattern cell."""
    size = 17 + 4 * version
    modules = _empty(size)
    reserved = _empty(size)

    def occupy(r: int, c: int, dark: bool) -> None:
        if 0 <= r < size and 0 <= c < size:
            modules[r][c] = dark
            reserved[r][c] = True

    def finder(r0: int, c0: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                inside_ring = (0 <= dr <= 6 and dc in (0, 6)) or \
                              (0 <= dc <= 6 and dr in (0, 6))
                core = 2 <= dr <= 4 and 2 <= dc <= 4
                occupy(r0 + dr, c0 + dc, inside_ring or core)

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    centers = _ALIGNMENT[version]
    n = len(centers)
    for ri, r in enumerate(centers):
        for ci, c in enumerate(centers):
            if (ri, ci) in {(0, 0), (0, n - 1), (n - 1, 0)}:
                continue  # overlaps finder patterns
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    ring = abs(dr) == 2 or abs(dc) == 2
                    center = dr == 0 and dc == 0
                    occupy(r + dr, c + dc, ring or center)

    for pos in range(size):
        if not reserved[6][pos]:
            occupy(6, pos, pos % 2 == 0)
        if not reserved[pos][6]:
            occupy(pos, 6, pos % 2 == 0)

    occupy(size - 8, 8, True)  # dark module

    # Reserve format-info areas (both copies) BEFORE data placement.
    def mark(r: int, c: int) -> None:
        if not reserved[r][c]:
            reserved[r][c] = True
            modules[r][c] = False
    for i in range(15):
        r1 = {i <= 5: (8, i), i == 6: (8, 7), i == 7: (8, 8),
              i == 8: (7, 8)}.get(True) or (14 - i, 8)
        mark(*r1)
        mark(*(size - 1 - i, 8) if i < 8 else (8, size - 15 + i))
    if version >= 7:  # version-info blocks
        for i in range(18):
            mark(i // 3, size - 11 + i % 3)
            mark(size - 11 + i % 3, i // 3)

    return modules, reserved


def _format_bits(ecl: str, mask: int) -> int:
    data = (_EC_FORMAT_BITS[ecl] << 3) | mask
    d = data << 10
    for i in range(14, 9, -1):
        if d >> i & 1:
            d ^= 0b10100110111 << (i - 10)
    return ((data << 10) | d) ^ 0b101010000010010


def _version_bits(version: int) -> int:
    d = version << 12
    for i in range(17, 11, -1):
        if d >> i & 1:
            d ^= 0b1111100100101 << (i - 12)
    return (version << 12) | d


def _place_format(modules, reserved, size, fmt: int) -> None:
    def put(r, c, bit):
        modules[r][c] = bool(bit)
        reserved[r][c] = True
    for i in range(15):
        bit = (fmt >> i) & 1
        if i <= 5:
            put(8, i, bit)
        elif i == 6:
            put(8, 7, bit)
        elif i == 7:
            put(8, 8, bit)
        elif i == 8:
            put(7, 8, bit)
        else:
            put(14 - i, 8, bit)
        if i < 8:
            put(size - 1 - i, 8, bit)
        else:
            put(8, size - 15 + i, bit)


def _place_version(modules, reserved, size, version: int) -> None:
    if version < 7:
        return
    bits = _version_bits(version)

    def put(r, c, bit):
        modules[r][c] = bool(bit)
        reserved[r][c] = True
    for i in range(18):
        bit = (bits >> i) & 1
        put(i // 3, size - 11 + i % 3, bit)
        put(size - 11 + i % 3, i // 3, bit)


def _raw_grid(codewords: list[int], version: int, reserved):
    """Place codeword bits (zigzag) leaving function cells untouched."""
    size = 17 + 4 * version
    grid: list[list[bool | None]] = [[None] * size for _ in range(size)]
    bits: list[int] = []
    for cw in codewords:
        for shift in range(7, -1, -1):
            bits.append((cw >> shift) & 1)
    bits.extend([0] * _REMAINDER_BITS[version])

    idx = 0
    upward = True
    right = size - 1
    while right > 0:
        if right == 6:
            right -= 1
        for step in range(size):
            r = (size - 1 - step) if upward else step
            for c in (right, right - 1):
                if reserved[r][c]:
                    continue
                bit = bits[idx] if idx < len(bits) else 0
                idx += 1
                grid[r][c] = bool(bit)
        upward = not upward
        right -= 2
    return grid


_MASK_FNS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def _apply_mask(grid, reserved, mask_id: int):
    fn = _MASK_FNS[mask_id]
    size = len(grid)
    out = _empty(size)
    for r in range(size):
        for c in range(size):
            if reserved[r][c] or grid[r][c] is None:
                out[r][c] = False
            else:
                out[r][c] = bool(grid[r][c]) ^ fn(r, c)
    return out


def _penalty(matrix) -> int:
    size = len(matrix)
    score = 0

    def line_score(get):
        run_color = None
        run_len = 0
        total = 0
        for i in range(size):
            v = get(i)
            if v == run_color:
                run_len += 1
            else:
                if run_len >= 5:
                    total += 3 + run_len - 5
                run_color, run_len = v, 1
        if run_len >= 5:
            total += 3 + run_len - 5
        return total

    for r in range(size):
        score += line_score(lambda c_, r_=r: matrix[r_][c_])
    for c in range(size):
        score += line_score(lambda r_, c_=c: matrix[r_][c_])

    for r in range(size - 1):
        for c in range(size - 1):
            v = matrix[r][c]
            if v is matrix[r][c + 1] and v is matrix[r + 1][c] and v is matrix[r + 1][c + 1]:
                score += 3

    pat1 = (True, False, True, True, True, False, True)
    for r in range(size):
        for c in range(size - 10):
            window_r = tuple(matrix[r][c + k] for k in range(11))
            if tuple(window_r[:7]) == pat1 and not any(window_r[7:]) :
                score += 40
            if not any(window_r[:4]) and tuple(window_r[4:]) == pat1:
                score += 40
    for r in range(size - 10):
        for c in range(size):
            window_c = tuple(matrix[r + k][c] for k in range(11))
            if tuple(window_c[:7]) == pat1 and not any(window_c[7:]):
                score += 40
            if not any(window_c[:4]) and tuple(window_c[4:]) == pat1:
                score += 40

    dark = sum(row.count(True) for row in matrix)
    percent = dark * 100 // (size * size)
    score += 10 * (abs(percent - 50) // 5)
    return score


def make(payload: str | bytes, ec_level: str = "M") -> list[list[bool]]:
    """Encode payload into a QR matrix (list of row lists, True = dark)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if ec_level not in ("L", "M", "Q", "H"):
        raise QRError(f"invalid EC level '{ec_level}'")

    order = [ec_level] + [l for l in ("M", "L", "Q", "H") if l != ec_level]
    chosen = None
    for version in range(1, MAX_VERSION + 1):
        for level in order:
            data_cw = _BLOCKS[version][level][0]
            cc_bits = 16 if version >= 10 else 8
            if 4 + cc_bits + 8 * len(payload) <= data_cw * 8:
                chosen = (version, level)
                break
        if chosen:
            break
    if not chosen:
        raise QRError(f"payload too long ({len(payload)} bytes) for versions 1-{MAX_VERSION}")

    version, level = chosen
    segment = _encode_segment(payload, version, level)
    stream = _interleave(version, level, segment)

    modules, reserved = _function_map(version)
    _place_version(modules, reserved, 17 + 4 * version, version)
    grid = _raw_grid(stream, version, reserved)

    best, best_score = None, None
    size = 17 + 4 * version
    for mask_id in range(8):
        masked = _apply_mask(grid, reserved, mask_id)
        # merge: start from function modules, overlay masked data cells
        merged = [row[:] for row in modules]
        for r in range(size):
            for c in range(size):
                if not reserved[r][c]:
                    merged[r][c] = masked[r][c]
        score = _penalty(merged)
        if best_score is None or score < best_score:
            best, best_score = (merged, mask_id, _format_bits(level, mask_id)), score

    merged, mask_id, fmt = best
    final_modules, final_reserved = _function_map(version)  # fresh reservation
    _place_version(final_modules, final_reserved, size, version)
    _place_format(final_modules, final_reserved, size, fmt)
    for r in range(size):
        for c in range(size):
            if not final_reserved[r][c]:
                final_modules[r][c] = merged[r][c]
    return final_modules


# --------------------------------------------------------------------------
# Verification (structural decode) — proves correctness in tests
# --------------------------------------------------------------------------

def verify_matrix(matrix, payload: str | bytes) -> None:
    """Decode structure back out of ``matrix`` and assert it matches payload."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    size = len(matrix)
    version = (size - 17) // 4
    if 17 + 4 * version != size:
        raise QRError("bad size")

    # --- format info: read second copy (independent of our writer's choices)
    fmt = 0
    for i in range(15):
        if i < 8:
            bit = matrix[size - 1 - i][8]
        else:
            bit = matrix[8][size - 15 + i]
        fmt |= bit << i
    fmt ^= 0b101010000010010
    rem = fmt & 0x3FF
    data5 = fmt >> 10
    d = data5 << 10
    for i in range(14, 9, -1):
        if d >> i & 1:
            d ^= 0b10100110111 << (i - 10)
    if d != rem:
        raise QRError("format BCH check failed")
    ecl_code = data5 >> 3
    mask_id = data5 & 0b111
    ecl_by_code = {0b01: "L", 0b00: "M", 0b11: "Q", 0b10: "H"}
    ecl = ecl_by_code[ecl_code]

    # --- rebuild reservation map identically to the writer
    _, reserved = _function_map(version)

    # --- unmask and collect data bits in placement order
    fn = _MASK_FNS[mask_id]
    bits: list[int] = []
    upward = True
    right = size - 1
    while right > 0:
        if right == 6:
            right -= 1
        for step in range(size):
            r = (size - 1 - step) if upward else step
            for c in (right, right - 1):
                if reserved[r][c]:
                    continue
                bits.append((1 if matrix[r][c] else 0) ^ (1 if fn(r, c) else 0))
        upward = not upward
        right -= 2

    data_cw_total, groups, ec_per_block = _BLOCKS[version][ecl]
    block_count = sum(count for count, _ in groups)
    total_cw = data_cw_total + block_count * ec_per_block
    codewords = []
    for i in range(0, total_cw * 8, 8):
        chunk = bits[i:i + 8]
        if len(chunk) < 8:
            raise QRError(f"short stream: ran out of bits at {i}")
        codewords.append(int("".join(map(str, chunk)), 2))

    # --- de-interleave (column-wise, mirroring the writer)
    per_block_sizes: list[int] = []
    for count, sz in groups:
        per_block_sizes.extend([sz] * count)
    max_data = max(per_block_sizes)
    data_blocks: list[list[int]] = [[] for _ in range(block_count)]
    ptr = 0
    for i in range(max_data):
        for bi in range(block_count):
            if i < per_block_sizes[bi]:
                data_blocks[bi].append(codewords[ptr])
                ptr += 1

    # --- RS consistency: parity recomputed from data must equal stored parity
    stored_ec = [[] for _ in range(block_count)]
    for i in range(ec_per_block):
        for bi in range(block_count):
            stored_ec[bi].append(codewords[data_cw_total + i * block_count + bi])
    for bi in range(block_count):
        recomputed = _rs_parity(data_blocks[bi], ec_per_block)
        if recomputed != stored_ec[bi]:
            raise QRError(f"Reed-Solomon mismatch in block {bi}")

    # Blocks were cut sequentially from the padded segment by the writer,
    # so payload reconstruction is a plain concatenation (NOT column-major).
    flat = [cw for block in data_blocks for cw in block]

    # --- strip mode/count header, compare payload
    stream = "".join(format(cw, "08b") for cw in flat)[:data_cw_total * 8]
    if stream[:4] != "0100":
        raise QRError("mode nibble mismatch")
    cc_bits = 16 if version >= 10 else 8
    length = int(stream[4:4 + cc_bits], 2)
    extracted = bytearray()
    for i in range(length):
        extracted.append(int(stream[4 + cc_bits + 8 * i:12 + cc_bits + 8 * i], 2))
    if bytes(extracted) != payload:
        raise QRError(
            f"payload mismatch: {bytes(extracted)!r} != {payload!r}"
        )


# --------------------------------------------------------------------------
# Output formats
# --------------------------------------------------------------------------

QUIET_ZONE = 4


def svg(matrix, module_px: int = 4, dark: str = "#111827", light: str = "#FFFFFF") -> str:
    size = len(matrix)
    dim = (size + QUIET_ZONE * 2) * module_px
    rects: list[str] = []
    for r, row in enumerate(matrix):
        c = 0
        while c < size:
            if row[c]:
                run = 1
                while c + run < size and row[c + run]:
                    run += 1
                x = (c + QUIET_ZONE) * module_px
                y = (r + QUIET_ZONE) * module_px
                rects.append(
                    f'<rect x="{x}" y="{y}" width="{run * module_px}" height="{module_px}"/>'
                )
                c += run
            else:
                c += 1
    body = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" '
        f'width="{dim}" height="{dim}" shape-rendering="crispEdges">'
        f'<rect width="{dim}" height="{dim}" fill="{light}"/>'
        f'<g fill="{dark}">{body}</g></svg>'
    )


def png_bytes(matrix, scale: int = 8) -> bytes:
    size = len(matrix)
    dim = (size + QUIET_ZONE * 2) * scale
    rows: list[bytes] = []
    blank = b"\x00" * dim
    rows.extend([blank] * QUIET_ZONE * scale)
    for row in matrix:
        line = bytearray(b"\xff" * dim)
        for r_off in range(scale):
            pixels = bytearray()
            pixels += b"\xff" * QUIET_ZONE * scale
            for cell in row:
                pixels += b"\x00" * scale if cell else b"\xff" * scale
            pixels += b"\xff" * QUIET_ZONE * scale
            line = bytes(pixels)
            rows.append(line)
    rows.extend([blank] * QUIET_ZONE * scale)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", dim, dim, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"".join(b"\x00" + r for r in rows), 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def wifi_payload(ssid: str, password: str, hidden: bool = False) -> str:
    def esc(value: str) -> str:
        out = []
        for ch in value:
            if ch in '\\;,:"':
                out.append("\\" + ch)
            else:
                out.append(ch)
        return "".join(out)

    parts = ["WIFI:T:WPA", f"S:{esc(ssid)}"]
    if password:
        parts.append(f"P:{esc(password)}")
    if hidden:
        parts.append("H:true")
    return ";".join(parts) + ";;"
