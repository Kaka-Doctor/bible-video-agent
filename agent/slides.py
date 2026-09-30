"""Compose and render the video slides (1920x1080) and the YouTube thumbnail."""
from __future__ import annotations

import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import theme
from .bible import Chapter, next_chapter
from .config import Settings
from .scriptgen import Script, Section
from .theme import PALETTE as P
from .theme import gradient

log = logging.getLogger("slides")

W, H = 1920, 1080
TW, TH = 1280, 720


class SlideRenderer:
    def __init__(self, settings: Settings):
        self.s = settings
        from .config import FONTS_DIR
        self.fonts = theme.FontBook(FONTS_DIR)

    # -- shared chrome ------------------------------------------------------

    def _canvas(self, seed: str, w: int = W, h: int = H) -> Image.Image:
        return theme.background(w, h, seed)

    def _wordmark(self, img: Image.Image, draw: ImageDraw.ImageDraw,
                  scale: float = 1.0):
        text = self.s.channel_name.upper()
        font = self.fonts.get("sans", "Medium", int(26 * scale))
        tracked = 7 * scale
        cross_tile = theme.cross(20 * scale)
        text_w = sum(draw.textlength(c, font=font) for c in text) + tracked * (len(text) - 1)
        total = cross_tile.width + 16 * scale + text_w
        cx, y = img.width / 2, 58 * scale
        theme.paste_center(img, cross_tile, cx - total / 2 + cross_tile.width / 2, y + 13 * scale)
        theme.draw_tracked(draw, cx + cross_tile.width / 2 + 8 * scale, y, text, font,
                           (*P["gold"], 220), tracking=tracked)

    def _footer(self, draw: ImageDraw.ImageDraw, reference: str,
                index: int, total: int):
        font = self.fonts.get("sans", "Regular", 24)
        draw.text((70, H - 66), f"{reference} · KJV", font=font,
                  fill=(*P["text_dim"], 180))
        if total <= 21:
            n = total
            spacing = 26
            x0 = W / 2 - spacing * (n - 1) / 2
            for i in range(n):
                filled = i <= index
                theme.diamond(draw, x0 + i * spacing, H - 52, 6,
                              (*P["gold"], 235) if filled else (*P["gold"], 70))
        draw.text((W - 70, H - 66), "ONE CHAPTER A DAY", font=font,
                  fill=(*P["text_dim"], 150), anchor="ra")

    # -- slides ---------------------------------------------------------------

    def title_slide(self, seed: str, book: str, chapter: int, subtitle: str) -> Image.Image:
        img = self._canvas(seed)
        d = ImageDraw.Draw(img, "RGBA")
        self._wordmark(img, d)

        font, lines, size = theme.fit_text(d, book.upper(), self.fonts,
                                           "display", "Black", 170, 1500, 2, min_size=90)
        total_h = len(lines) * size * 1.12
        y = 300 - total_h / 2
        for line in lines:
            theme.draw_centered(d, W / 2, y, line, font, (*P["gold_bright"], 255))
            y += size * 1.12

        theme.flourish(d, W / 2, y + 28, 460)

        label = f"CHAPTER {chapter}"
        lf = self.fonts.get("sans", "SemiBold", 46)
        theme.draw_tracked(d, W / 2, y + 78, label, lf, (*P["gold"], 235), tracking=10)

        sub_font, sub_lines, sub_size = theme.fit_text(
            d, subtitle, self.fonts, "serif_italic", "Medium Italic", 48, 1250, 2, min_size=30)
        sy = y + 190
        for line in sub_lines:
            theme.draw_centered(d, W / 2, sy, line, sub_font, (*P["text"], 235))
            sy += sub_size * 1.35
        return img

    def _points_block(self, d, points: list[str], y_top: float) -> float:
        """Left-aligned bullet points, centered as a block. Returns bottom y."""
        font = self.fonts.get("sans", "Regular", 44)
        max_w = max(theme.text_width(d, p, font) for p in points) if points else 0
        block_w = min(max_w + 46, 1380)
        x = W / 2 - block_w / 2 + 23
        y = y_top
        line_h = 44 * 1.5
        for point in points:
            theme.diamond(d, x - 30, y + 27, 8, (*P["gold"], 235))
            for li, line in enumerate(theme.wrap_text(d, point, font, block_w - 46)):
                d.text((x, y), line, font=font, fill=(*P["text"], 240))
                y += 44 * 1.28
            y += line_h - 44 * 1.28
        return y

    def section_slide(self, seed: str, section: Section, reference: str,
                      index: int, total: int) -> Image.Image:
        img = self._canvas(seed)
        d = ImageDraw.Draw(img, "RGBA")
        self._wordmark(img, d)

        font, lines, size = theme.fit_text(
            d, section.title, self.fonts, "display", "Bold", 78, 1420, 2, min_size=44)
        y = 175
        for line in lines:
            theme.draw_centered(d, W / 2, y, line, font, (*P["gold_bright"], 255))
            y += size * 1.15
        theme.flourish(d, W / 2, y + 24, 380)

        if section.on_screen:
            self._points_block(d, section.on_screen, y + 90)
        else:
            vfont = self.fonts.get("serif_italic", "Medium Italic", 44)
            vlines = theme.wrap_text(d, section.narration[:220] + "…", vfont, 1150)
            vy = y + 110
            for line in vlines[:5]:
                theme.draw_centered(d, W / 2, vy, line, vfont, (*P["text"], 225))
                vy += 60

        self._footer(d, reference, index, total)
        return img

    def jesus_slide(self, seed: str, section: Section, reference: str,
                    index: int, total: int) -> Image.Image:
        img = self._canvas(seed)
        d = ImageDraw.Draw(img, "RGBA")
        self._wordmark(img, d)

        # signature cross
        cross_tile = theme.cross(150)
        theme.paste_center(img, cross_tile, W / 2, 250)

        chip_font = self.fonts.get("sans", "SemiBold", 34)
        label = "SEEING JESUS"
        lw = theme.draw_tracked(d, W / 2, 368, label, chip_font,
                                (*P["gold"], 245), tracking=12)
        d.line([W / 2 - lw / 2 - 90, 385, W / 2 - lw / 2 - 24, 385],
               fill=(*P["gold"], 160), width=2)
        d.line([W / 2 + lw / 2 + 24, 385, W / 2 + lw / 2 + 90, 385],
               fill=(*P["gold"], 160), width=2)

        font, lines, size = theme.fit_text(
            d, section.title, self.fonts, "display", "Bold", 64, 1420, 2, min_size=40)
        y = 430
        for line in lines:
            theme.draw_centered(d, W / 2, y, line, font, (*P["gold_bright"], 255))
            y += size * 1.15
        if section.on_screen:
            self._points_block(d, section.on_screen, y + 60)
        self._footer(d, reference, index, total)
        return img

    def verse_slide(self, seed: str, reference: str, verse_ref: str,
                    text: str, index: int, total: int) -> Image.Image:
        img = self._canvas(seed)
        d = ImageDraw.Draw(img, "RGBA")
        self._wordmark(img, d)

        # oversized opening quotation mark
        qfont = self.fonts.get("serif", "Bold", 210)
        d.text((W / 2 - 560, 165), "\u201C", font=qfont, fill=(*P["gold"], 120))

        font, lines, size = theme.fit_text(
            d, text, self.fonts, "serif_italic", "Medium Italic", 54, 1340, 11, min_size=26)
        line_h = size * 1.42
        block_h = len(lines) * line_h
        y = max(340, 540 - block_h / 2)
        for line in lines:
            theme.draw_centered(d, W / 2, y, line, font, (*P["text"], 245))
            y += line_h

        ref_font = self.fonts.get("sans", "SemiBold", 34)
        theme.draw_tracked(d, W / 2, min(y + 40, 950), verse_ref.upper(),
                           ref_font, (*P["gold"], 245), tracking=9)
        self._footer(d, reference, index, total)
        return img

    def application_slide(self, seed: str, section: Section, reference: str,
                          index: int, total: int) -> Image.Image:
        img = self._canvas(seed)
        d = ImageDraw.Draw(img, "RGBA")
        self._wordmark(img, d)

        font, lines, size = theme.fit_text(
            d, section.title, self.fonts, "display", "Bold", 74, 1420, 2, min_size=44)
        y = 175
        for line in lines:
            theme.draw_centered(d, W / 2, y, line, font, (*P["gold_bright"], 255))
            y += size * 1.15
        theme.flourish(d, W / 2, y + 24, 380)

        points = section.on_screen[:3]
        text_font = self.fonts.get("sans", "Regular", 42)
        num_font = self.fonts.get("display", "Bold", 40)
        row_h = 118
        y0 = y + 96
        for i, point in enumerate(points):
            cy = y0 + i * row_h + 30
            d.ellipse([W / 2 - 560, cy - 30, W / 2 - 500, cy + 30],
                      outline=(*P["gold"], 225), width=3)
            d.text((W / 2 - 530, cy - 26), str(i + 1), font=num_font,
                   fill=(*P["gold_bright"], 255), anchor="ma")
            plines = theme.wrap_text(d, point, text_font, 900)
            py = cy - (len(plines) - 1) * 27
            for line in plines:
                d.text((W / 2 - 455, py - 26), line, font=text_font,
                       fill=(*P["text"], 240))
                py += 54
        self._footer(d, reference, index, total)
        return img

    def outro_slide(self, seed: str, reference: str, next_ref: str,
                    index: int, total: int) -> Image.Image:
        img = self._canvas(seed)
        d = ImageDraw.Draw(img, "RGBA")
        self._wordmark(img, d)

        chip_font = self.fonts.get("sans", "SemiBold", 34)
        theme.draw_tracked(d, W / 2, 235, "TOMORROW", chip_font,
                           (*P["gold"], 235), tracking=14)

        font, lines, size = theme.fit_text(
            d, next_ref, self.fonts, "display", "Bold", 105, 1400, 2, min_size=60)
        y = 320
        for line in lines:
            theme.draw_centered(d, W / 2, y, line, font, (*P["gold_bright"], 255))
            y += size * 1.15
        theme.flourish(d, W / 2, y + 30, 420)

        cta_font = self.fonts.get("sans", "Regular", 42)
        theme.draw_centered(d, W / 2, y + 110, "Subscribe for a new chapter every day",
                            cta_font, (*P["text"], 235))
        theme.draw_centered(d, W / 2, y + 175, self.s.channel_url.split("//")[1],
                            self.fonts.get("sans", "Medium", 34), (*P["text_dim"], 220))

        cross_tile = theme.cross(64)
        theme.paste_center(img, cross_tile, W / 2, y + 265)
        self._footer(d, reference, index, total)
        return img

    # -- thumbnail ---------------------------------------------------------------
    #
    # A dedicated, high-impact YouTube composition (not a scaled-down slide):
    #   dramatic navy backdrop + god-rays + glowing cross on the left,
    #   massive metallic-gold book name, gold "CHAPTER N" badge and a punchy
    #   white hook line on the right — engineered to stay readable at
    #   mobile-feed size.

    def _epic_background(self, seed: str) -> Image.Image:
        img = gradient(TW, TH, [
            (0.0, (6, 10, 26)), (0.55, (16, 24, 52)), (1.0, (8, 13, 32)),
        ]).convert("RGBA")
        focus = (TW * 0.225, TH * 0.47)
        img = theme.radial_glow(img, focus, TH * 0.72, alpha=64, blur=140)
        img = theme.god_rays(img, focus, seed, n=13)
        # sparse starfield
        rng = random.Random(f"{seed}-stars")
        overlay = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for _ in range(70):
            x, y = rng.uniform(0, TW), rng.uniform(0, TH)
            a = int(rng.uniform(25, 80))
            r = rng.choice((1, 1, 2))
            od.ellipse([x - r, y - r, x + r, y + r],
                       fill=(*P["star"], a))
        img = Image.alpha_composite(img, overlay)
        # strong vignette for edge drama
        vig = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vig)
        vd.rounded_rectangle([0, 0, TW, TH], radius=int(TH * 0.12),
                             fill=(0, 0, 0, 0), outline=(0, 0, 0, 255),
                             width=int(TH * 0.30))
        vig = vig.filter(ImageFilter.GaussianBlur(150))
        img = Image.alpha_composite(img, vig)
        return img

    @staticmethod
    def _short_hook(hook: str, max_words: int = 4) -> str:
        words = [w.strip(" ,.:;—-–\"'()") for w in hook.split()]
        words = [w for w in words if w][:max_words]
        phrase = " ".join(words).strip()
        return phrase.upper()[:26]

    def thumbnail(self, seed: str, book: str, chapter: int, hook: str) -> Image.Image:
        img = self._epic_background(seed + "-thumb")

        # --- left: glowing cross (bigger, vertically centered) ---
        focus = (TW * 0.235, TH * 0.50)
        halo = theme.radial_glow(
            Image.new("RGBA", (TW, TH), (0, 0, 0, 0)), focus, TH * 0.40,
            color=(240, 214, 140), alpha=95, blur=95)
        img = Image.alpha_composite(img, halo)
        cross_tile = theme.cross(TH * 0.58)
        theme.paste_center(img, cross_tile, focus[0], focus[1])
        # sparkle glints around the cross
        rng = random.Random(f"{seed}-glints")
        gl = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        for _ in range(9):
            x = focus[0] + rng.uniform(-TH * 0.60, TH * 0.60)
            y = focus[1] + rng.uniform(-TH * 0.55, TH * 0.55)
            s = rng.uniform(5, 13)
            c = (*P["gold_bright"], int(rng.uniform(120, 210)))
            gd.line([x - s, y, x + s, y], fill=c, width=2)
            gd.line([x, y - s, x, y + s], fill=c, width=2)
        img = Image.alpha_composite(img, gl)

        # --- right: text block (no handle — YouTube already shows the
        #     channel name under every thumbnail, so the space goes to type) ---
        cx = TW * 0.685
        right_w = TW - int(TW * 0.40) - 40  # usable width for the block

        # 1) chapter badge — solid gold chip, navy type, slight tilt
        badge_font = self.fonts.get("sans", "ExtraBold", 58)
        badge_text = f"CHAPTER {chapter}"
        bd = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        tw_ = bd.textlength(badge_text, font=badge_font)
        asc, desc = badge_font.getmetrics()
        pad_x, pad_y = 38, 16
        bw, bh = int(tw_) + pad_x * 2, asc + desc + pad_y * 2 - 8
        badge = Image.new("RGBA", (bw + 16, bh + 16), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(badge)
        chip = Image.new("RGB", (bw, bh))
        chip.paste(theme.gradient(bw, bh, [
            (0.0, (250, 232, 160)), (0.5, (222, 184, 62)), (1.0, (176, 138, 48)),
        ]), (0, 0))
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=16,
                                                fill=255)
        badge.paste(chip, (8, 8), mask)
        bdraw.rounded_rectangle([8, 8, 8 + bw - 1, 8 + bh - 1], radius=16,
                                outline=(120, 90, 26, 255), width=3)
        bdraw.text((8 + pad_x, 8 + pad_y - 6), badge_text, font=badge_font,
                   fill=(10, 17, 40, 255))
        badge = badge.rotate(-2.5, expand=True, resample=Image.BICUBIC)

        # 2) hook tiles — punchy white caps (built FIRST: the book name is
        #    then sized to whatever vertical budget remains). Prefer ONE big
        #    line; fall back to two balanced lines that actually fit.
        phrase = self._short_hook(hook or f"{book} {chapter}")
        hook_tiles: list[Image.Image] = []

        def _hook_tile(text: str, hfont) -> Image.Image:
            return theme.gradient_text_tile(
                text, hfont,
                stops=[(0.0, (255, 255, 255)), (1.0, (226, 232, 248))],
                stroke_width=max(4, hfont.size // 14))

        if phrase:
            single = None
            for hsize in range(88, 44, -4):  # single line, as big as possible
                hfont = self.fonts.get("sans", "ExtraBold", hsize)
                htile = _hook_tile(phrase, hfont)
                if htile.width <= right_w:
                    single = htile
                    break
            if single is not None:
                hook_tiles = [single]
            else:  # two balanced lines, shrinking until every line fits
                words = phrase.split()
                for hsize in range(68, 36, -4):
                    hfont = self.fonts.get("sans", "ExtraBold", hsize)
                    # choose the split point that minimizes the widest line
                    candidates = []
                    for m in range(1, len(words)):
                        lines = [" ".join(words[:m]), " ".join(words[m:])]
                        lines = [ln for ln in lines if ln]
                        if len(lines) != 2:
                            continue
                        tiles = [_hook_tile(ln, hfont) for ln in lines]
                        candidates.append((max(t.width for t in tiles), tiles))
                    if candidates:
                        widest, tiles = min(candidates, key=lambda c: c[0])
                        if widest <= right_w:
                            hook_tiles = tiles
                            break
                if not hook_tiles:  # extreme fallback: truncate to 3 words
                    hfont = self.fonts.get("sans", "ExtraBold", 44)
                    short = " ".join(phrase.split()[:3])
                    hook_tiles = [_hook_tile(short, hfont)]

        # 3) book name — massive metallic gold. Numeric prefixes ("1 John")
        #    are split off and rendered smaller so the name itself stays
        #    huge. The name is sized to BOTH the block width and the
        #    remaining vertical budget so the whole stack can never
        #    overflow the canvas (bug found by box-measurement QA).
        raw = book.upper().strip()
        prefix = ""
        parts = raw.split(" ", 1)
        if len(parts) == 2 and parts[0] in {"1", "2", "3", "I", "II", "III"}:
            prefix, raw = parts[0], parts[1]

        gap_name_badge, gap_badge_hook, line_gap = 22, 40, 8
        margin = 56
        hook_h = (sum(t.height for t in hook_tiles)
                  + line_gap * max(len(hook_tiles) - 1, 0))
        budget_h = (TH - 2 * margin - gap_name_badge - badge.height
                    - (gap_badge_hook + hook_h if hook_tiles else 0))
        size = 210
        while size >= 96:
            font = self.fonts.get("display", "Black", size)
            tile = theme.gradient_text_tile(
                raw, font, stroke_width=max(5, size // 16))
            if (tile.width <= right_w - (size * 0.75 if prefix else 0)
                    and tile.height <= budget_h):
                break
            size -= 8

        # 4) dynamic vertical centering of the whole text stack
        stack_h = (tile.height + gap_name_badge + badge.height
                   + (gap_badge_hook + hook_h if hook_tiles else 0))
        y = max(margin, (TH - stack_h) / 2)

        # name (prefix hangs to the left of it, baseline-ish aligned)
        name_cx = cx - (size * 0.31 if prefix else 0)
        theme.paste_with_shadow(img, tile, name_cx, y + tile.height / 2,
                                offset=(0, 12), blur=16, alpha=180)
        if prefix:
            pf_font = self.fonts.get("display", "Black", int(size * 0.58))
            ptile = theme.gradient_text_tile(
                prefix, pf_font, stroke_width=max(3, int(size * 0.58) // 16))
            theme.paste_with_shadow(
                img, ptile, name_cx - tile.width / 2 - ptile.width / 2 - 14,
                y + ptile.height / 2 - 6,
                offset=(0, 8), blur=10, alpha=160)
        y += tile.height + gap_name_badge

        # badge
        theme.paste_with_shadow(img, badge, cx, y + badge.height / 2,
                                offset=(0, 9), blur=11, alpha=170)
        y += badge.height + gap_badge_hook

        # hook block
        for htile in hook_tiles:
            theme.paste_with_shadow(img, htile, cx, y + htile.height / 2,
                                    offset=(0, 8), blur=10, alpha=170)
            y += htile.height + line_gap

        # --- chrome: keyline frame + corner diamonds ---
        d = ImageDraw.Draw(img, "RGBA")
        m = 26
        d.rounded_rectangle([m, m, TW - m, TH - m], radius=14,
                            outline=(*P["gold"], 150), width=3)
        theme.corner_diamonds(d, TW, TH, m, r=11)
        return img.convert("RGB")

    # -- orchestration -------------------------------------------------------

    def render_all(self, script: Script, chapter: Chapter,
                   out_dir: Path) -> list[Path]:
        """Render every slide; returns ordered list of PNG paths."""
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        total = len(script.sections)
        seed_base = f"{chapter.book}-{chapter.chapter}"
        hook = script.thumbnail_hook or chapter.reference
        book2, ch2 = next_chapter(chapter.book, chapter.chapter)
        next_ref = f"{book2} {ch2}"

        for i, sec in enumerate(script.sections):
            seed = f"{seed_base}-{i}"
            if sec.type == "verse":
                text = chapter.verse_text(sec.verse_numbers)
                nums = sorted(sec.verse_numbers)
                ref = (f"{chapter.book} {chapter.chapter}:{nums[0]}" if len(nums) == 1
                       else f"{chapter.book} {chapter.chapter}:{nums[0]}-{nums[-1]}")
                img = self.verse_slide(seed, chapter.reference, ref, text, i, total)
            elif sec.type == "jesus":
                img = self.jesus_slide(seed, sec, chapter.reference, i, total)
            elif sec.type == "application":
                img = self.application_slide(seed, sec, chapter.reference, i, total)
            elif sec.type == "outro":
                img = self.outro_slide(seed, chapter.reference, next_ref, i, total)
            elif sec.type == "intro":
                img = self.title_slide(seed, chapter.book, chapter.chapter,
                                       script.hook or hook)
                # keep footer consistent — title slide skips footer by design
            else:  # context / explanation
                img = self.section_slide(seed, sec, chapter.reference, i, total)

            path = out_dir / f"slide_{i:02d}.png"
            img.save(path, "PNG")
            paths.append(path)
            log.debug("Rendered %s (%s)", path.name, sec.type)

        thumb = self.thumbnail(seed_base, chapter.book, chapter.chapter, hook)
        thumb_path = out_dir / "thumbnail.png"
        thumb.save(thumb_path, "PNG")
        log.info("Rendered %d slides + thumbnail in %s", len(paths), out_dir)
        return paths
