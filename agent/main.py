"""Orchestrate one daily run: fetch → script → slides → narration → video → upload.

Run manually:
    python -m agent.main                       # today's chapter (from state.json)
    python -m agent.main --book John --chapter 1
    python -m agent.main --script-file examples/john1_script.json --no-upload
    python -m agent.main --no-upload           # render only (dry run)
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import qa
from . import state as state_mod
from .bible import fetch_chapter, next_chapter, normalize_book
from .config import OUTPUT_DIR, ROOT, Settings, WORK_DIR
from .scriptgen import generate_script, load_script_file
from .slides import SlideRenderer
from .tts import synth_sections
from .video import probe_duration, render_video

log = logging.getLogger("main")


def _banner(title: str) -> None:
    log.info("=" * 62)
    log.info(title)
    log.info("=" * 62)


def build_tags(book: str, chapter: int, settings: Settings) -> list[str]:
    tags = [
        book, f"{book} {chapter}", f"{book} chapter {chapter}",
        "Bible study", "Bible summary", "KJV", "Jesus",
        "daily devotional", "Bible explained",
        settings.channel_name,
    ]
    tags.extend(settings.extra_tags)
    # YouTube limit: 500 chars across all tags
    out, used = [], 0
    for t in tags:
        if used + len(t) + 1 > 480:
            break
        out.append(t)
        used += len(t) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily Bible video agent")
    parser.add_argument("--book", help="override book (e.g. John)")
    parser.add_argument("--chapter", type=int, help="override chapter number")
    parser.add_argument("--script-file", help="use a fixed script JSON instead of AI")
    parser.add_argument("--no-upload", action="store_true",
                        help="render the video but do not upload")
    parser.add_argument("--keep-state", action="store_true",
                        help="do not advance state.json")
    parser.add_argument("--force", action="store_true",
                        help="bypass the once-per-day guard (posts even if "
                             "today's video is already live)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    settings = Settings.from_env()
    if args.book:
        settings.book_override = args.book
    if args.chapter:
        settings.chapter_override = args.chapter
    if args.script_file:
        settings.script_file = args.script_file
    if args.no_upload:
        settings.dry_run = True
    if args.keep_state:
        settings.keep_state = True
    if args.force:
        settings.force_upload = True

    started = time.time()

    # 1. Which chapter? ------------------------------------------------------
    st = state_mod.load(settings=settings)
    book = normalize_book(settings.book_override or st["next"]["book"])
    chapter = settings.chapter_override or st["next"]["chapter"]
    _banner(f"TODAY: {book} {chapter} — {settings.channel_name}")

    # 1b. ONCE-PER-DAY GUARD -------------------------------------------------
    # Exactly one video per EAT calendar day, no matter how many times the
    # workflow is triggered (delayed cron, manual run, re-run, …).
    if (not settings.dry_run and not settings.force_upload
            and state_mod.posted_today(st)):
        lv = st.get("last_video") or {}
        log.info("ONCE-PER-DAY GUARD: today's video is already live (%s). "
                 "The channel posts exactly one video per day — skipping "
                 "this run. Use --force / FORCE_UPLOAD to override.",
                 lv.get("url", "(unknown url)"))
        return 0

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 2. Fetch the text ------------------------------------------------------
    chapter_data = fetch_chapter(book, chapter, settings.translation)

    # 3. Write the script ----------------------------------------------------
    if settings.script_file:
        script = load_script_file(settings.script_file, chapter_data)
    else:
        script = generate_script(chapter_data, settings)
    log.info("Script ready (%d words, %d sections, source=%s)",
             script.word_count, len(script.sections), script.source)

    # 3b. SCRIPT QUALITY GATE -------------------------------------------------
    script_checks = qa.check_script(script, settings)
    qa.log_checks("SCRIPT QA", script_checks)
    if not all(c.passed for c in script_checks):
        qa.write_report(out_dir / "qa_report.json", script_checks,
                        stage="script", book=book, chapter=chapter,
                        script_words=script.word_count,
                        script_source=script.source)
        for c in script_checks:
            if not c.passed:
                log.error("SCRIPT QA FAIL — %s: %s", c.name, c.detail)
        log.error("The script does not meet the channel guidelines — "
                  "refusing to render or upload. State NOT advanced; "
                  "%s %d will be retried on the next run.", book, chapter)
        return 1

    # 4. Slides ---------------------------------------------------------------
    work = WORK_DIR
    if work.exists():
        shutil.rmtree(work)
    renderer = SlideRenderer(settings)
    slides = renderer.render_all(script, chapter_data, work / "slides")

    # 5. Narration ------------------------------------------------------------
    narrations = []
    for sec in script.sections:
        text = sec.narration
        if sec.type == "intro" and script.hook:
            text = f"{script.hook} {text}".strip()
        narrations.append(text)
    wavs = synth_sections(narrations, settings.voice, settings.tts_rate,
                          work / "audio")

    # 6. Video ------------------------------------------------------------------
    slug = f"{book.lower().replace(' ', '_')}_chapter_{chapter}"
    video_path = out_dir / f"{slug}.mp4"
    stats = render_video(slides, wavs, video_path,
                         ken_burns=settings.ken_burns, work_dir=work / "segments")

    # 7. Thumbnail (JPEG for the API) -------------------------------------------
    from PIL import Image
    thumb_png = work / "slides" / "thumbnail.png"
    thumb_jpg = out_dir / f"{slug}_thumb.jpg"
    Image.open(thumb_png).convert("RGB").save(thumb_jpg, "JPEG", quality=92)

    # 8. Description with chapter timestamps --------------------------------------
    section_chapters: list[tuple[str, float]] = []
    t_cursor = 0.0
    for sec, wav in zip(script.sections, wavs):
        section_chapters.append((sec.title or sec.type.title(), t_cursor))
        t_cursor += probe_duration(wav)
    from .youtube import build_description
    description = build_description(script.description, chapter_data.reference,
                                    section_chapters, settings)
    title = settings.video_title(book, chapter)
    tags = build_tags(book, chapter, settings)

    # 8b. QUALITY GATE — the video must earn its upload -----------------------
    video_checks = qa.check_video(video_path, stats, settings)
    packaging_checks = qa.check_packaging(title, description, thumb_jpg)
    qa.log_checks("VIDEO QA", video_checks + packaging_checks)
    qa_passed = qa.write_report(
        out_dir / "qa_report.json", script_checks + video_checks + packaging_checks,
        book=book, chapter=chapter, script_words=script.word_count,
        script_source=script.source,
        duration_seconds=round(stats["duration"], 1), title=title)
    if not qa_passed:
        for c in video_checks + packaging_checks:
            if not c.passed:
                log.error("VIDEO QA FAIL — %s: %s", c.name, c.detail)
        log.error("QUALITY GATE FAILED — %s %d does not meet the channel "
                  "guidelines, so it will NOT be uploaded. State NOT "
                  "advanced; the chapter is retried on the next run.",
                  book, chapter)
        return 1
    log.info("QUALITY GATE PASSED (%d checks green) — clear to upload.",
             len(script_checks) + len(video_checks) + len(packaging_checks))

    # 9. Upload ---------------------------------------------------------------------
    video_id, video_url = "", ""
    if settings.dry_run:
        log.info("DRY RUN — skipping upload (video saved at %s)", video_path)
    elif not settings.has_youtube_credentials:
        log.warning("YouTube credentials not set (YT_CLIENT_ID / "
                    "YT_CLIENT_SECRET / YT_REFRESH_TOKEN) — skipping upload. "
                    "The finished video is at %s", video_path)
    else:
        from .youtube import set_thumbnail, upload_video
        result = upload_video(video_path, title, description, tags, settings)
        video_id, video_url = result["video_id"], result["url"]
        set_thumbnail(video_id, thumb_jpg, settings)
        log.info("LIVE: %s", video_url)

    # 10. Persist metadata + advance state --------------------------------------------
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "book": book,
        "chapter": chapter,
        "reference": chapter_data.reference,
        "title": title,
        "description": description,
        "tags": tags,
        "video_id": video_id,
        "video_url": video_url,
        "video_file": str(video_path),
        "thumbnail_file": str(thumb_jpg),
        "duration_seconds": round(stats["duration"], 1),
        "script_source": script.source,
        "script_words": script.word_count,
        "qa_passed": qa_passed,
        "uploaded": bool(video_id),
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (out_dir / "last_script.json").write_text(
        json.dumps({
            "hook": script.hook, "thumbnail_hook": script.thumbnail_hook,
            "description": script.description,
            "sections": [vars(s) for s in script.sections],
        }, indent=2) + "\n", encoding="utf-8")

    if video_id and not settings.keep_state:
        state_mod.advance(ROOT / "state.json", book, chapter,
                          video_url, video_id)
    elif settings.keep_state:
        log.info("State not advanced (--keep-state).")

    log.info("Done in %.1f min. Next chapter: %s %s", (time.time() - started) / 60,
             *next_chapter(book, chapter))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("main").critical("RUN FAILED: %s", exc, exc_info=True)
        sys.exit(1)
