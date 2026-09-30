"""Visual theme system for slide rendering.

The default (and currently only) theme is 'royal_gold': a deep navy-indigo
gradient with a subtle starfield, a double gold frame, Cinzel display
serifs, EB Garamond scripture text and Inter UI type.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

PALETTE = {
    # background gradient stops (top -> bottom)
    "bg_stops": [(0.0, (10, 17, 40)), (0.5, (22, 33, 63)), (1.0, (13, 22, 46))],
    "gold": (212, 175, 55),
    "gold_bright": (240, 217, 140),
    "gold_deep": (156, 122, 44),
    "text": (245, 241, 230),
    "text_dim": (185, 194, 216),
    "star": (200, 214, 255),
}

# ---------------------------------------------------------------------------
# Font book (variable fonts with named instances)
# ---------------------------------------------------------------------------

FAMILIES = {
    "display": "Cinzel[wght].ttf",
    "serif": "EBGaramond[wght].ttf",
    "serif_italic": "EBGaramond-Italic[wght].ttf",
    "sans": "Inter[opsz,wght].ttf",
}


class FontBook:
    """Cached loader that resolves variable-font named instances."""

    def __init__(self, fonts_dir: Path):
        self.dir = Path(fonts_dir)
        self._cache: dict[tuple, ImageFont.FreeTypeFont] = {}

    def get(self, family: str, instance: str, size: int) -> ImageFont.FreeTypeFont:
        key = (family, instance, size)
        if key in self._cache:
            return self._cache[key]
        path = self.dir / FAMILIES[family]
        font = ImageFont.truetype(str(path), size)
        try:
            names = font.get_variation_names()
            names = [n.decode() if isinstance(n, bytes) else n for n in names]
            if instance in names:
                font.set_variation_by_name(instance)
        except Exception:  # variation support missing — default instance is fine
            pass
        self._cache[key] = font
        return font


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font)


def wrap_text(draw, text: str, font, max_width: float) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if text_width(draw, trial, font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(draw, text: str, fontbook: FontBook, family: str, instance: str,
             start_size: int, max_width: float, max_lines: int,
             min_size: int = 22):
    """Shrink font size until text fits max_width x max_lines. Returns
    (font, lines, size)."""
    size = start_size
    while size >= min_size:
        font = fontbook.get(family, instance, size)
        lines = wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines, size
        size -= 4
    font = fontbook.get(family, instance, min_size)
    lines = wrap_text(draw, text, font, max_width)[:max_lines]
    return font, lines, min_size


def draw_centered(draw, cx: float, y: float, text: str, font, fill,
                  anchor: str = "ma"):
    draw.text((cx, y), text, font=font, fill=fill, anchor=anchor)


def draw_tracked(draw, cx: float, y: float, text: str, font, fill,
                 tracking: float = 6.0):
    """Centered text with letter tracking (letter-spacing)."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + tracking
    return total


# ---------------------------------------------------------------------------
# Background & ornaments
# ---------------------------------------------------------------------------

def _lerp(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(w: int, h: int, stops) -> Image.Image:
    column = Image.new("RGB", (1, h))
    px = column.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                local = (t - t0) / max(t1 - t0, 1e-6)
                px[0, y] = _lerp(c0, c1, local)
                break
        else:
            px[0, y] = stops[-1][1]
    return column.resize((w, h))


def background(w: int, h: int, seed_key: str) -> Image.Image:
    """Navy gradient + starfield + soft gold glow + vignette + gold frame."""
    p = PALETTE
    img = gradient(w, h, p["bg_stops"])
    rng = random.Random(seed_key)

    # starfield
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for _ in range(150):
        x, y = rng.uniform(0, w), rng.uniform(0, h * 0.92)
        depth = 1 - (y / h)  # denser/brighter near top
        alpha = int(rng.uniform(30, 90) + 70 * max(depth, 0))
        r = rng.choice((1, 1, 1, 2))
        color = p["star"] if rng.random() > 0.12 else p["gold"]
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*color, min(alpha, 255)))
    for _ in range(6):  # sparkle glints
        x, y = rng.uniform(60, w - 60), rng.uniform(40, h * 0.5)
        s = rng.uniform(4, 9)
        c = (*p["star"], rng.randint(60, 110))
        d.line([x - s, y, x + s, y], fill=c, width=1)
        d.line([x, y - s, x, y + s], fill=c, width=1)
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    # soft radial glow behind the title zone
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([w * 0.18, -h * 0.25, w * 0.82, h * 0.55],
               fill=(*p["gold"], 22))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img, glow)

    # vignette
    vig = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    vd.rounded_rectangle([0, 0, w, h], radius=int(h * 0.10),
                         fill=(0, 0, 0, 0), outline=(0, 0, 0, 255),
                         width=int(h * 0.22))
    vig = vig.filter(ImageFilter.GaussianBlur(160))
    img = Image.alpha_composite(img, vig)

    # double gold frame
    frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(frame)
    m = 30
    fd.rounded_rectangle([m, m, w - m, h - m], radius=18,
                         outline=(*p["gold"], 165), width=2)
    m2 = 42
    fd.rounded_rectangle([m2, m2, w - m2, h - m2], radius=12,
                         outline=(*p["gold"], 70), width=1)
    img = Image.alpha_composite(img, frame)
    return img.convert("RGB")


def cross(size: float, color=PALETTE["gold"], glow=True) -> Image.Image:
    """A latin cross rendered on a transparent RGBA tile, size = height."""
    pad = int(size * 0.65)
    w = int(size * 0.62) + pad * 2
    h = int(size) + pad * 2
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    cx = w / 2
    bar_w = max(int(size * 0.075), 3)
    v_len = size
    h_len = size * 0.58
    y0 = pad
    # vertical beam
    d.rounded_rectangle(
        [cx - bar_w / 2, y0, cx + bar_w / 2, y0 + v_len],
        radius=bar_w / 2, fill=(*color, 235))
    # horizontal beam (placed slightly above center — latin proportions)
    hy = y0 + v_len * 0.30
    d.rounded_rectangle(
        [cx - h_len / 2, hy - bar_w / 2, cx + h_len / 2, hy + bar_w / 2],
        radius=bar_w / 2, fill=(*color, 235))
    if glow:
        glow_tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_tile)
        gd.rounded_rectangle([cx - bar_w, y0 - bar_w, cx + bar_w, y0 + v_len + bar_w],
                             radius=bar_w, fill=(*color, 110))
        gd.rounded_rectangle([cx - h_len / 2 - bar_w / 2, hy - bar_w,
                              cx + h_len / 2 + bar_w / 2, hy + bar_w],
                             radius=bar_w, fill=(*color, 110))
        glow_tile = glow_tile.filter(ImageFilter.GaussianBlur(size * 0.12))
        tile = Image.alpha_composite(glow_tile, tile)
    return tile


def diamond(draw, cx, cy, r, fill, outline=None):
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                 fill=fill, outline=outline)


def flourish(draw, cx: float, y: float, width: float, color=PALETTE["gold"]):
    """Thin gold rule with a center diamond — used under headings."""
    half = width / 2
    draw.line([cx - half, y, cx - 14, y], fill=(*color, 190), width=2)
    draw.line([cx + 14, y, cx + half, y], fill=(*color, 190), width=2)
    diamond(draw, cx, y, 7, (*color, 235))
    diamond(draw, cx, y, 3, (10, 17, 40))


def paste_center(base: Image.Image, tile: Image.Image, cx: float, cy: float):
    base.paste(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)), tile)


# ---------------------------------------------------------------------------
# Epic YouTube thumbnail engine
# ---------------------------------------------------------------------------

# metallic gold ramp used for the big display text
GOLD_TEXT_STOPS = [
    (0.0, (250, 232, 160)),
    (0.45, (222, 184, 62)),
    (0.75, (196, 152, 44)),
    (1.0, (138, 103, 34)),
]


def gradient_text_tile(text: str, font, stops=GOLD_TEXT_STOPS,
                       stroke_width: int = 0, stroke_fill=(8, 12, 30),
                       tracking: float = 0.0) -> Image.Image:
    """Render one line of text with a vertical gradient fill, outline and
    optional letter tracking on a transparent RGBA tile."""
    # measure (with tracking) on a scratch surface
    scratch = Image.new("RGBA", (8, 8))
    sd = ImageDraw.Draw(scratch)
    if tracking:
        widths = [sd.textlength(ch, font=font) for ch in text]
        text_w = sum(widths) + tracking * max(len(text) - 1, 0)
    else:
        text_w = sd.textlength(text, font=font)
    asc, desc = font.getmetrics()
    w = int(text_w) + 2 * stroke_width + 12
    h = asc + desc + 2 * stroke_width + 12

    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)

    def _draw_text(fill, stroke_fill_, stroke_w):
        if tracking:
            x = 6 + stroke_width
            for ch, cw in zip(text, widths):
                td.text((x, 6 + stroke_width), ch, font=font, fill=fill,
                        stroke_width=stroke_w, stroke_fill=stroke_fill_)
                x += cw + tracking
        else:
            td.text((6 + stroke_width, 6 + stroke_width), text, font=font,
                    fill=fill, stroke_width=stroke_w, stroke_fill=stroke_fill_)

    if stroke_width:  # dark outline underlay
        _draw_text((*stroke_fill, 255), (*stroke_fill, 255), stroke_width)
    # gradient fill through the glyph mask
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    if tracking:
        x = 6 + stroke_width
        for ch, cw in zip(text, widths):
            md.text((x, 6 + stroke_width), ch, font=font, fill=255)
            x += cw + tracking
    else:
        md.text((6 + stroke_width, 6 + stroke_width), text, font=font, fill=255)
    grad = gradient(w, h, stops)
    tile.paste(grad, (0, 0), mask)
    return tile


def paste_with_shadow(base: Image.Image, tile: Image.Image, cx: float, cy: float,
                      offset=(0, 10), blur=14, alpha=170):
    """Paste a tile centered at (cx, cy) with a soft drop shadow beneath."""
    x, y = int(cx - tile.width / 2), int(cy - tile.height / 2)
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, alpha), (x + offset[0], y + offset[1]), tile.split()[3])
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh)
    base.paste(tile, (x, y), tile)


def god_rays(img: Image.Image, focus: tuple[float, float], seed_key: str,
             n: int = 13, min_len: float = 0.42, max_len: float = 0.98,
             color=(232, 196, 96)) -> Image.Image:
    """Radiating translucent light wedges from a focus point (epic backlight)."""
    rng = random.Random(f"rays-{seed_key}")
    w, h = img.size
    rays = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    max_r = (w ** 2 + h ** 2) ** 0.5
    for i in range(n):
        ang = (i / n) * 360 + rng.uniform(-8, 8)
        spread = rng.uniform(2.2, 5.5)
        ln = max_r * rng.uniform(min_len, max_len)
        pts = [focus]
        for da in (-spread / 2, spread / 2):
            a = math.radians(ang + da)
            pts.append((focus[0] + ln * math.cos(a), focus[1] + ln * math.sin(a)))
        rd.polygon(pts, fill=(*color, int(rng.uniform(14, 34))))
    rays = rays.filter(ImageFilter.GaussianBlur(7))
    return Image.alpha_composite(img.convert("RGBA"), rays).convert("RGBA")


def radial_glow(img: Image.Image, focus: tuple[float, float], radius: float,
                color=(222, 184, 62), alpha: int = 70, blur: int = 130) -> Image.Image:
    """Soft circular glow behind a focal point."""
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([focus[0] - radius, focus[1] - radius,
                focus[0] + radius, focus[1] + radius],
               fill=(*color, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def corner_diamonds(draw: ImageDraw.ImageDraw, w: int, h: int, inset: int,
                    r: int = 9, color=PALETTE["gold"]):
    for cx, cy in ((inset, inset), (w - inset, inset),
                   (inset, h - inset), (w - inset, h - inset)):
        draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                     fill=(*color, 220))
