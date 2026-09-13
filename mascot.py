"""Cute mascot drawn programmatically with PIL.

We render once at startup and cache the result. Two variants:
  • default   — a soft purple flower with a sleepy smile
  • celebrating — same flower but with a sparkle around it (for empty state)

Returns a PIL.Image you can wrap in CTkImage for display."""
from __future__ import annotations

import math
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None  # type: ignore


def _hex_to_rgba(h: str, a: int = 255) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def draw_flower(size: int = 128,
                petal_color: str = "#E89BAB",
                petal_shade: str = "#C2607A",
                center_color: str = "#E8C595",
                cheek_color: str = "#F7C6D1",
                ink: str = "#3B2D33") -> Optional["Image.Image"]:
    """Soft pink-petalled flower with a sleepy little face. Returns RGBA Image."""
    if not HAS_PIL:
        return None

    # Render at 2x then downscale — gives smooth, antialiased edges
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx, cy = s // 2, s // 2
    petal_r = int(s * 0.27)
    petal_dist = int(s * 0.26)

    # 5 petals, slightly offset so the flower feels alive
    for i in range(5):
        angle = (i * 72 - 90) * math.pi / 180
        px = cx + petal_dist * math.cos(angle)
        py = cy + petal_dist * math.sin(angle)
        # outer petal
        d.ellipse((px - petal_r, py - petal_r, px + petal_r, py + petal_r),
                  fill=_hex_to_rgba(petal_color))
        # inner highlight
        hr = int(petal_r * 0.55)
        d.ellipse((px - hr, py - hr - hr * 0.2, px + hr, py + hr - hr * 0.2),
                  fill=_hex_to_rgba("#FFFFFF", 70))

    # Center
    cr = int(s * 0.22)
    d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr),
              fill=_hex_to_rgba(center_color))
    # Center inner shade for depth
    cir = int(cr * 0.78)
    d.ellipse((cx - cir, cy - cir, cx + cir, cy + cir),
              fill=_hex_to_rgba("#FFE294"))

    # Cheeks
    cheek_r = int(s * 0.05)
    for dx in (-int(s * 0.10), int(s * 0.10)):
        d.ellipse((cx + dx - cheek_r, cy + cheek_r - 2,
                   cx + dx + cheek_r, cy + cheek_r * 3 - 2),
                  fill=_hex_to_rgba(cheek_color, 200))

    # Sleepy eyes — closed arcs
    eye_w = int(s * 0.045)
    eye_offset = int(s * 0.07)
    for ex in (cx - eye_offset, cx + eye_offset):
        d.arc((ex - eye_w, cy - eye_w // 2 - 2,
               ex + eye_w, cy + eye_w // 2),
              start=200, end=340, fill=_hex_to_rgba(ink), width=max(2, s // 80))

    # Small smile
    smile_w = int(s * 0.07)
    d.arc((cx - smile_w, cy + 2, cx + smile_w, cy + smile_w + 6),
          start=20, end=160, fill=_hex_to_rgba(ink), width=max(2, s // 90))

    # Downscale for smoothness
    img = img.resize((size, size), Image.LANCZOS)
    return img


def draw_sparkle(size: int = 16, color: str = "#F5C04D") -> Optional["Image.Image"]:
    """Tiny 4-point sparkle for decoration."""
    if not HAS_PIL:
        return None
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = s // 2, s // 2
    # Vertical diamond
    d.polygon([(cx, 0), (cx + s // 6, cy), (cx, s), (cx - s // 6, cy)],
              fill=_hex_to_rgba(color))
    # Horizontal diamond
    d.polygon([(0, cy), (cx, cy + s // 6), (s, cy), (cx, cy - s // 6)],
              fill=_hex_to_rgba(color))
    return img.resize((size, size), Image.LANCZOS)


# Lazy singletons so we draw only once
_cache: dict = {}


def get_mascot(size: int = 128) -> Optional["Image.Image"]:
    key = ("flower", size)
    if key not in _cache:
        _cache[key] = draw_flower(size=size)
    return _cache[key]


def get_sparkle(size: int = 16) -> Optional["Image.Image"]:
    key = ("sparkle", size)
    if key not in _cache:
        _cache[key] = draw_sparkle(size=size)
    return _cache[key]
