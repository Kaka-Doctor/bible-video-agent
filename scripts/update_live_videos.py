"""Retrofit already-live channel videos: epic thumbnails + Play Store footer.

For every upload whose title matches the agent pattern
    "Summary of the book of {book} - Chapter {N} || Biblia Tafsiri Mbalimbali"
this script:
  1. parses the book + chapter,
  2. generates a punchy 3-5 word thumbnail hook (Gemini, with a verse-anchored
     fallback so it never fails),
  3. renders the NEW epic thumbnail (agent/slides.py),
  4. appends the Play Store app link to the description (idempotent),
  5. updates the video metadata (title/tags/category preserved) and sets the
     custom thumbnail.

Run from GitHub Actions (needs GEMINI_API_KEY + YT_* secrets) or locally with
the same env vars. Optional VIDEO_ID env limits the run to one video.

Usage:
    python scripts/update_live_videos.py            # all agent videos
    VIDEO_ID=Ad-yN8jZCCc python scripts/update_live_videos.py
    DRY_RUN=1 python scripts/update_live_videos.py  # preview only
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

# make the agent package importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from agent.bible import fetch_chapter, normalize_book
from agent.config import Settings
from agent.scriptgen import _call_gemini
from agent.slides import SlideRenderer
from agent.youtube import (_access_token, append_app_link, set_thumbnail)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("retrofit")

TITLE_RE = re.compile(
    r"^Summary of the book of (?P<book>.+?) - Chapter (?P<ch>\d+)\s*\|\|",
    re.IGNORECASE)

API = "https://www.googleapis.com/youtube/v3"


def hook_for(book: str, chapter: int, settings: Settings) -> str:
    """A punchy 3-5 word hook for the thumbnail. Gemini first; verse-1
    fallback keeps the retrofit alive through any AI outage."""
    prompt = (f"Give ONE punchy YouTube-thumbnail hook phrase of 3 to 5 words "
              f"(ALL words meaningful, no filler) that captures the drama or "
              f"theme of {book} chapter {chapter} in the Bible. Reply with "
              f"ONLY the phrase — no quotes, no punctuation, no explanation.")
    try:
        text, source = _call_gemini(prompt, settings)
        words = text.strip().strip('"\'').split()
        if 2 <= len(words) <= 6:
            phrase = " ".join(w.strip(".,:;!?—-") for w in words)
            log.info("hook (via %s): %s", source, phrase)
            return phrase
    except Exception as exc:  # noqa: BLE001
        log.warning("Gemini hook failed (%s) — using verse fallback", exc)
    try:
        ch = fetch_chapter(book, chapter, settings.translation)
        first = ch.verse_text([ch.verses[0].number])
        words = [w for w in re.split(r"\s+", first.strip()) if w][:6]
        phrase = " ".join(words).strip(" ,.:;")
        log.info("hook (verse fallback): %s", phrase)
        return phrase
    except Exception as exc:  # noqa: BLE001
        log.warning("Verse fallback failed too (%s) — generic hook", exc)
        return f"{book} {chapter}"


def main() -> int:
    settings = Settings.from_env()
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
    only_id = os.environ.get("VIDEO_ID", "").strip()

    if not settings.has_youtube_credentials:
        log.error("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN not set")
        return 1
    token = _access_token(settings.yt_client_id, settings.yt_client_secret,
                          settings.yt_refresh_token)
    auth = {"Authorization": f"Bearer {token}"}

    # 1. uploads playlist
    r = requests.get(f"{API}/channels", params={"part": "contentDetails,snippet",
                                                "mine": "true"},
                     headers=auth, timeout=60)
    r.raise_for_status()
    ch = r.json()["items"][0]
    uploads_id = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    log.info("channel: %s (%s)", ch["snippet"]["title"], uploads_id)

    # 2. all uploads (2 pages = 100 videos is plenty)
    videos: list[dict] = []
    page_token = ""
    while True:
        params = {"part": "snippet,contentDetails", "maxResults": 50,
                  "playlistId": uploads_id}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{API}/playlistItems", params=params, headers=auth,
                         timeout=60)
        r.raise_for_status()
        data = r.json()
        videos.extend(data.get("items", []))
        page_token = data.get("nextPageToken", "")
        if not page_token or len(videos) >= 100:
            break
    log.info("uploads found: %d", len(videos))

    renderer = SlideRenderer(settings)
    updated, skipped = 0, 0

    for item in videos:
        vid = item["snippet"]["resourceId"]["videoId"]
        title = item["snippet"]["title"]
        if only_id and vid != only_id:
            continue
        m = TITLE_RE.match(title)
        if not m:
            log.info("skip (not an agent video): %s", title[:60])
            skipped += 1
            continue
        book = normalize_book(m.group("book").strip())
        chapter = int(m.group("ch"))

        # 3. current video snippet
        r = requests.get(f"{API}/videos", params={"part": "snippet", "id": vid},
                         headers=auth, timeout=60)
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            log.warning("video %s gone (%s)", vid, title[:50])
            continue
        snip = items[0]["snippet"]

        new_desc = append_app_link(snip.get("description", ""))
        desc_changed = new_desc != snip.get("description", "")

        # 4. render the new epic thumbnail
        hook = hook_for(book, chapter, settings)
        thumb_img = renderer.thumbnail(f"{book}-{chapter}", book, chapter, hook)
        tmp = Path(tempfile.mkdtemp())
        thumb_jpg = tmp / "thumb.jpg"
        thumb_img.save(thumb_jpg, "JPEG", quality=92)

        log.info("%s %d (%s): desc_changed=%s hook=%r",
                 book, chapter, vid, desc_changed, hook)
        if dry_run:
            log.info("DRY RUN — would update description + thumbnail")
            continue

        # 5. update description (title/tags/category preserved)
        if desc_changed:
            body = {"id": vid, "snippet": {
                "title": snip["title"],
                "description": new_desc[:4900],
                "categoryId": snip.get("categoryId", "27"),
            }}
            if snip.get("tags"):
                body["snippet"]["tags"] = snip["tags"][:30]
            r = requests.put(f"{API}/videos", params={"part": "snippet"},
                             headers={**auth, "Content-Type": "application/json"},
                             json=body, timeout=60)
            if r.status_code in (200, 201):
                log.info("description updated (%s)", vid)
            else:
                log.error("description update failed HTTP %d: %s",
                          r.status_code, r.text[:300])

        # 6. set the new thumbnail
        if set_thumbnail(vid, thumb_jpg, settings):
            log.info("epic thumbnail set (%s)", vid)
        updated += 1

    log.info("DONE — updated %d, skipped %d", updated, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
