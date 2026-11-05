"""Generate the extension icons without third-party image libraries.

The icon is an original BugPilot mark: a dark rounded tile with a lime bug
scout (shell, head, visor). Run with `python scripts/make_icons.py`.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "apps" / "extension" / "icons"

BG = (16, 17, 20, 255)
BORDER = (132, 204, 22, 255)
SHELL = (132, 204, 22, 255)
SHELL_DARK = (60, 92, 12, 255)
HEAD = (76, 112, 20, 255)
EYE = (11, 12, 14, 255)


def new_canvas(size: int) -> list[list[tuple[int, int, int, int]]]:
    return [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]


def put(canvas, x: int, y: int, color) -> None:
    if 0 <= y < len(canvas) and 0 <= x < len(canvas):
        canvas[y][x] = color


def rounded_rect(canvas, x0, y0, x1, y1, radius, color) -> None:
    for y in range(y0, y1):
        for x in range(x0, x1):
            dx = max(x0 + radius - x, 0, x - (x1 - 1 - radius))
            dy = max(y0 + radius - y, 0, y - (y1 - 1 - radius))
            if dx * dx + dy * dy <= radius * radius:
                put(canvas, x, y, color)


def rect(canvas, x0, y0, x1, y1, color) -> None:
    for y in range(y0, y1):
        for x in range(x0, x1):
            put(canvas, x, y, color)


def ellipse(canvas, cx, cy, rx, ry, color) -> None:
    for y in range(int(cy - ry), int(cy + ry) + 1):
        for x in range(int(cx - rx), int(cx + rx) + 1):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                put(canvas, x, y, color)


def write_png(path: Path, canvas) -> None:
    height = len(canvas)
    width = len(canvas[0])
    raw = bytearray()
    for row in canvas:
        raw.append(0)
        for pixel in row:
            raw.extend(pixel)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", header)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def draw(size: int):
    canvas = new_canvas(size)
    s = size / 128.0
    rounded_rect(canvas, 0, 0, size, size, int(26 * s) or 1, BG)
    # lime border
    rounded_rect(canvas, 0, 0, size, size, int(26 * s) or 1, BORDER)
    rounded_rect(
        canvas,
        max(1, int(2 * s)),
        max(1, int(2 * s)),
        size - max(1, int(2 * s)),
        size - max(1, int(2 * s)),
        int(24 * s) or 1,
        BG,
    )

    # shell
    ellipse(canvas, 64 * s, 76 * s, 27 * s, 23 * s, SHELL)
    # wing highlight
    ellipse(canvas, 40 * s, 52 * s, 15 * s, 9 * s, (215, 245, 167, 120))
    ellipse(canvas, 88 * s, 52 * s, 15 * s, 9 * s, (215, 245, 167, 120))
    # head
    ellipse(canvas, 64 * s, 44 * s, 18 * s, 17 * s, HEAD)
    # visor
    rect(canvas, int(51 * s), int(39 * s), int(77 * s), int(49 * s), EYE)
    ellipse(canvas, 58 * s, 44 * s, 3 * s, 3 * s, SHELL)
    ellipse(canvas, 58 * s, 44 * s, 1.4 * s, 1.4 * s, (234, 255, 176, 255))
    ellipse(canvas, 70 * s, 44 * s, 3 * s, 3 * s, SHELL)
    ellipse(canvas, 70 * s, 44 * s, 1.4 * s, 1.4 * s, (234, 255, 176, 255))
    # centre seam
    rect(canvas, int(63 * s), int(56 * s), max(int(63 * s) + 1, int(65 * s)), int(98 * s), SHELL_DARK)
    # legs
    for start, end in (
        ((42, 82), (26, 94)),
        ((46, 92), (32, 104)),
        ((86, 82), (102, 94)),
        ((82, 92), (96, 104)),
    ):
        steps = int(14 * s) or 1
        for i in range(steps):
            t = i / steps
            x = int((start[0] + (end[0] - start[0]) * t) * s)
            y = int((start[1] + (end[1] - start[1]) * t) * s)
            ellipse(canvas, x, y, max(1.0, 2 * s), max(1.0, 2 * s), SHELL_DARK)
    # antennae
    for start, end in (((56, 30), (46, 16)), ((72, 30), (82, 16))):
        steps = int(16 * s) or 1
        for i in range(steps):
            t = i / steps
            x = int((start[0] + (end[0] - start[0]) * t) * s)
            y = int((start[1] + (end[1] - start[1]) * t) * s)
            ellipse(canvas, x, y, max(1.0, 1.6 * s), max(1.0, 1.6 * s), HEAD)
        ellipse(canvas, end[0] * s, end[1] * s, max(1.5, 3 * s), max(1.5, 3 * s), SHELL)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        write_png(OUT / f"icon{size}.png", draw(size))
        print("wrote", OUT / f"icon{size}.png")


if __name__ == "__main__":
    main()
