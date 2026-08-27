from __future__ import annotations

import struct
import zlib
from typing import Iterable

RGB = tuple[int, int, int]

# ---------------------------------------------------------------- palette
TEAL = (15, 118, 110)
TEAL_DEEP = (11, 90, 84)
TEAL_SOFT = (142, 197, 190)
TERRA = (194, 112, 61)
TERRA_SOFT = (226, 168, 128)
SAND = (247, 242, 234)
CREAM = (252, 249, 243)
INK = (35, 42, 49)
WHITE = (255, 255, 255)
LEAF = (74, 103, 65)
LEAF_DARK = (47, 74, 48)
WOOD = (166, 124, 82)
GOLD = (233, 196, 106)


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


class Canvas:
    def __init__(self, w: int, h: int, bg: RGB = WHITE):
        self.w, self.h = w, h
        self.px: list[list[RGB]] = [[bg for _ in range(w)] for _ in range(h)]

    # -- primitives ---------------------------------------------------------
    def vgrad(self, y0: int, y1: int, top: RGB, bottom: RGB) -> None:
        span = max(1, y1 - y0)
        for y in range(max(0, y0), min(self.h, y1)):
            c = _mix(top, bottom, (y - y0) / span)
            row = self.px[y]
            for x in range(self.w):
                row[x] = c

    def rect(self, x: float, y: float, w: float, h: float, c: RGB,
             alpha: float = 1.0) -> None:
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(self.w, int(x + w)), min(self.h, int(y + h))
        for yy in range(y0, y1):
            row = self.px[yy]
            if alpha >= 0.999:
                for xx in range(x0, x1):
                    row[xx] = c
            else:
                base_row = row
                for xx in range(x0, x1):
                    base_row[xx] = _mix(base_row[xx], c, alpha)

    def circle(self, cx: float, cy: float, r: float, c: RGB,
               alpha: float = 1.0) -> None:
        y0, y1 = max(0, int(cy - r)), min(self.h - 1, int(cy + r))
        x0, x1 = max(0, int(cx - r)), min(self.w - 1, int(cx + r))
        r2 = r * r
        for yy in range(y0, y1 + 1):
            dy = yy - cy
            half = (r2 - dy * dy) ** 0.5 if dy * dy <= r2 else 0
            if half <= 0:
                continue
            row = self.px[yy]
            for xx in range(max(x0, int(cx - half)), min(x1 + 1, int(cx + half) + 1)):
                row[xx] = row[xx] if alpha < 0.999 else c
                if alpha < 0.999:
                    row[xx] = _mix(row[xx], c, alpha)

    def poly(self, pts: Iterable[tuple[float, float]], c: RGB) -> None:
        nodes = list(pts)
        if len(nodes) < 3:
            return
        ys = [p[1] for p in nodes]
        for y in range(max(0, int(min(ys))), min(self.h - 1, int(max(ys))) + 1):
            xs: list[float] = []
            j = len(nodes) - 1
            for i, (xi, yi) in enumerate(nodes):
                yj, xj = nodes[j][1], nodes[j][0]
                if (yi <= y < yj) or (yj <= y < yi):
                    xs.append(xi + (y - yi) / (yj - yi) * (xj - xi))
                j = i
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                xa, xb = int(xs[k]), int(xs[k + 1]) + 1
                row = self.px[y]
                for xx in range(max(0, xa), min(self.w, xb)):
                    row[xx] = c

    # -- output --------------------------------------------------------------
    def png_bytes(self) -> bytes:
        raw = bytearray()
        for row in self.px:
            raw.append(0)
            for r, g, b in row:
                raw += bytes((r, g, b))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data +
                    struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(bytes(raw), 7))
                + chunk(b"IEND", b""))

    def save(self, path: str) -> str:
        with open(path, "wb") as fh:
            fh.write(self.png_bytes())
        return path


# ------------------------------------------------------------------ scenes

def scene_exterior(w: int = 1600, h: int = 1000) -> Canvas:
    cv = Canvas(w, h)
    horizon = int(h * 0.62)
    cv.vgrad(0, horizon, TERRA_SOFT, GOLD)          # dusk sky
    cv.circle(int(w * 0.30), horizon - 150, 95, WHITE, alpha=0.92)
    cv.vgrad(horizon, int(h * 0.80), TEAL_SOFT, TEAL)   # sea
    cv.rect(0, int(h * 0.80), w, h - int(h * 0.80), SAND)  # deck

    # villa block (right side)
    vx, vw = int(w * 0.52), int(w * 0.40)
    vy = int(h * 0.34)
    vh = int(h * 0.46)
    cv.poly([(vx - 40, vy), (vx + vw + 40, vy), (vx + vw, vy - 60), (vx, vy - 60)], TERRA)
    cv.rect(vx, vy, vw, vh, CREAM)
    for r in range(2):                                   # windows
        for cidx in range(3):
            wx = vx + 60 + cidx * ((vw - 120) // 3 + 26)
            wy = vy + 70 + r * 160
            cv.rect(wx, wy, 96, 96, TEAL_SOFT)
            cv.rect(wx, wy, 96, 12, TEAL)
    cv.rect(vx + vw // 2 - 55, vy + vh - 170, 110, 170, TEAL_DEEP)  # door

    # cypress trees (left)
    for i, (cx, ch_) in enumerate([(w * 0.10, 300), (w * 0.17, 380), (w * 0.245, 260)]):
        base = int(h * 0.80)
        cv.poly([(cx, base - ch_), (cx + 42, base), (cx - 42, base)],
                LEAF_DARK if i % 2 else LEAF)

    # parasol by the pool edge
    px_, py_ = int(w * 0.38), int(h * 0.86)
    cv.rect(px_ - 5, py_, 10, 70, WOOD)
    cv.poly([(px_ - 130, py_), (px_ + 130, py_), (px_, py_ - 85)], TERRA)
    return cv


def scene_living(w: int = 1400, h: int = 900) -> Canvas:
    cv = Canvas(w, h)
    floor_y = int(h * 0.72)
    cv.vgrad(0, floor_y, SAND, CREAM)
    cv.rect(0, floor_y, w, h - floor_y, _mix(TERRA, WHITE, 0.45))
    # arch window with sea view
    ax, aw = int(w * 0.58), 300
    ay = int(h * 0.16)
    ah = int(h * 0.42)
    cv.rect(ax, ay, aw, ah, TEAL_SOFT)
    cv.circle(ax + aw // 2, ay, aw // 2, TEAL_SOFT)
    cv.rect(ax + 14, ay + 8, aw - 28, ah - 22, _mix(TEAL, TEAL_SOFT, 0.35))
    cv.circle(ax + aw // 2, ay, aw // 2 - 14, _mix(TEAL, TEAL_SOFT, 0.35))
    cv.circle(ax + int(aw * 0.32), ay + int(ah * 0.55), 26, GOLD, alpha=0.85)
    # sofa
    sx, sy = int(w * 0.10), floor_y - 210
    cv.rect(sx, sy + 60, 520, 130, TEAL)
    cv.rect(sx + 20, sy, 480, 80, _mix(TEAL, INK, 0.12))
    cv.rect(sx - 26, sy + 40, 46, 160, _mix(TEAL, INK, 0.2))
    cv.rect(sx + 500, sy + 40, 46, 160, _mix(TEAL, INK, 0.2))
    for cx_ in (sx + 120, sx + 320):
        cv.rect(cx_, sy + 66, 90, 64, SAND)
    # coffee table + bowl
    cv.rect(sx + 180, sy + 220, 200, 18, WOOD)
    cv.circle(sx + 280, sy + 208, 26, TERRA)
    # plant
    cv.poly([(w * 0.88, floor_y), (w * 0.93, floor_y), (w * 0.905, floor_y - 120)], TERRA)
    cv.circle(w * 0.905, floor_y - 165, 52, LEAF)
    cv.circle(w * 0.87, floor_y - 130, 36, LEAF_DARK)
    cv.circle(w * 0.94, floor_y - 135, 34, LEAF)
    # wall art
    cv.rect(w * 0.16, int(h * 0.14), 150, 110, CREAM)
    cv.rect(w * 0.16 + 10, int(h * 0.14) + 10, 130, 90, TERRA_SOFT)
    return cv


def scene_kitchen(w: int = 1400, h: int = 900) -> Canvas:
    cv = Canvas(w, h)
    counter_y = int(h * 0.56)
    cv.vgrad(0, counter_y, CREAM, SAND)
    cv.rect(0, counter_y, w, int(h * 0.13), TEAL)             # counters
    cv.rect(0, counter_y, w, 14, _mix(TEAL, WHITE, 0.35))     # worktop lip
    cv.rect(0, counter_y + int(h * 0.13), w, h, _mix(TERRA, WHITE, 0.5))
    # tile backsplash
    tile = 46
    for yy in range(counter_y - 240, counter_y - 6, tile):
        for xx in range(0, w, tile):
            cv.rect(xx + 2, yy + 2, tile - 4, tile - 4, WHITE)
    # hood
    cv.poly([(int(w * 0.36), counter_y - 250), (int(w * 0.64), counter_y - 250),
             (int(w * 0.58), counter_y - 140), (int(w * 0.42), counter_y - 140)], TEAL_DEEP)
    # shelf + jars
    cv.rect(int(w * 0.08), counter_y - 210, 300, 12, WOOD)
    for i, jc in enumerate((TERRA_SOFT, TEAL_SOFT, GOLD)):
        cv.rect(int(w * 0.09) + i * 90, counter_y - 262, 54, 52, jc)
    # pots on hob
    cv.circle(int(w * 0.44), counter_y - 18, 26, INK)
    cv.circle(int(w * 0.50), counter_y - 22, 20, _mix(INK, WHITE, 0.25))
    # fruit bowl
    cv.circle(int(w * 0.78), counter_y - 24, 34, GOLD)
    cv.circle(int(w * 0.77), counter_y - 44, 16, TERRA)
    cv.circle(int(w * 0.81), counter_y - 42, 15, LEAF)
    return cv


def scene_bedroom(w: int = 1400, h: int = 900) -> Canvas:
    cv = Canvas(w, h)
    floor_y = int(h * 0.76)
    cv.vgrad(0, floor_y, _mix(TEAL_SOFT, WHITE, 0.55), SAND)
    cv.rect(0, floor_y, w, h - floor_y, WOOD)
    # headboard + bed
    hx = int(w * 0.30)
    cv.rect(hx, floor_y - 330, 520, 120, _mix(WOOD, INK, 0.25))
    cv.rect(hx - 30, floor_y - 230, 580, 150, WHITE)
    cv.rect(hx - 30, floor_y - 110, 580, 40, TERRA)
    cv.rect(hx + 20, floor_y - 205, 150, 62, CREAM)
    cv.rect(hx + 330, floor_y - 205, 150, 62, CREAM)
    # side tables + lamps
    for lx in (hx - 150, hx + 550):
        cv.rect(lx, floor_y - 150, 100, 100, _mix(WOOD, WHITE, 0.2))
        cv.circle(lx + 50, floor_y - 175, 30, GOLD)
        cv.circle(lx + 50, floor_y - 178, 30, _mix(GOLD, WHITE, 0.35))
    # framed prints
    for fx, fw, fh_, fc in ((w * 0.12, 120, 150, TEAL_SOFT),
                            (w * 0.20, 120, 150, TERRA_SOFT)):
        cv.rect(fx, int(h * 0.16), fw, fh_, CREAM)
        cv.rect(fx + 12, int(h * 0.16) + 12, fw - 24, fh_ - 24, fc)
    # rug
    cv.rect(int(w * 0.24), floor_y + 40, 600, 70, _mix(TERRA, WHITE, 0.6))
    return cv


def scene_pool(w: int = 1400, h: int = 900) -> Canvas:
    cv = Canvas(w, h)
    water_y = int(h * 0.30)
    cv.vgrad(0, water_y, GOLD, TERRA_SOFT)
    cv.circle(int(w * 0.78), water_y - 110, 80, WHITE, alpha=0.9)
    cv.vgrad(water_y, h, TEAL, TEAL_DEEP)
    for i in range(6):                                   # ripples
        ry = water_y + 60 + i * 85
        cv.rect(int(w * 0.08) + (i % 2) * 90, ry, int(w * 0.55), 10,
                _mix(TEAL_SOFT, WHITE, 0.4), alpha=0.5)
    # deck strip
    cv.rect(0, 0, int(w * 0.16), h, SAND)
    cv.rect(int(w * 0.155), 0, 14, h, CREAM)
    # ladder
    lxx = int(w * 0.30)
    for off in (0, 70):
        cv.rect(lxx + off, water_y - 40, 12, 190, WHITE)
    for r in range(3):
        cv.rect(lxx, water_y + 10 + r * 55, 82, 10, WHITE)
    # float ring
    cv.circle(int(w * 0.62), int(h * 0.62), 74, TERRA)
    cv.circle(int(w * 0.62), int(h * 0.62), 34, TEAL)
    return cv


def logo_mark(size: int = 512, letter_bg: RGB = TEAL) -> Canvas:
    cv = Canvas(size, size, bg=letter_bg)
    pad = size // 8
    inner = size - pad * 2
    # mountain + sun monogram inside an implied rounded frame
    cv.poly([(pad, size - pad), (size // 2, pad + inner // 4),
             (size - pad, size - pad)], WHITE)
    cv.poly([(pad + inner // 8, size - pad), (size // 2 + inner // 10, size - pad),
             (size // 2, size - pad - inner // 3)], _mix(WHITE, TEAL_SOFT, 0.75))
    cv.circle(size - pad - inner // 5, pad + inner // 5, inner // 10, GOLD)
    return cv


SCENES = {
    "cover-exterior": scene_exterior,
    "living-room": scene_living,
    "kitchen": scene_kitchen,
    "master-bedroom": scene_bedroom,
    "pool-deck": scene_pool,
}


def generate_all(out_dir: str) -> dict[str, str]:
    """Write the full demo set; returns {name: file_path}."""
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for name, builder in SCENES.items():
        path = out / f"{name}.png"
        builder().save(str(path))
        files[name] = str(path)
    logo_path = out / "operator-logo.png"
    logo_mark().save(str(logo_path))
    files["logo"] = str(logo_path)
    return files
