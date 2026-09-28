"""Compose and render the video slides (1920x1080) and the YouTube thumbnail."""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

from . import theme
from .bible import Chapter, next_chapter
from .config import Settings
from .scriptgen import Script, Section
from .theme import PALETTE as P

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

    def thumbnail(self, seed: str, book: str, chapter: int, hook: str) -> Image.Image:
        img = self._canvas(seed + "-thumb", TW, TH)
        d = ImageDraw.Draw(img, "RGBA")

        # re-draw frame scaled for thumbnail
        m = 20
        d.rounded_rectangle([m, m, TW - m, TH - m], radius=12,
                            outline=(*P["gold"], 165), width=2)

        self._wordmark(img, d, scale=0.72)

        font, lines, size = theme.fit_text(
            d, book.upper(), self.fonts, "display", "Black", 150, 1060, 2, min_size=72)
        y = 150
        for line in lines:
            theme.draw_centered(d, TW / 2, y, line, font, (*P["gold_bright"], 255))
            y += size * 1.1

        label = f"CHAPTER {chapter}"
        lf = self.fonts.get("sans", "SemiBold", 44)
        theme.draw_tracked(d, TW / 2, y + 26, label, lf, (*P["gold"], 245), tracking=9)

        hook_font, hook_lines, hook_size = theme.fit_text(
            d, hook, self.fonts, "serif_italic", "SemiBold Italic", 60, 1000, 2, min_size=34)
        hy = y + 120
        for line in hook_lines:
            theme.draw_centered(d, TW / 2, hy, line, hook_font, (*P["text"], 250))
            hy += hook_size * 1.3

        theme.flourish(d, TW / 2, TH - 120, 360)
        handle_font = self.fonts.get("sans", "Medium", 28)
        theme.draw_tracked(d, TW / 2, TH - 95, self.s.channel_handle.upper(),
                           handle_font, (*P["gold"], 220), tracking=6)
        return img

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
