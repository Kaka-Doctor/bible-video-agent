"""Track which chapter comes next (persisted in state.json in the repo)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .bible import next_chapter, normalize_book
from .config import STATE_FILE, Settings

log = logging.getLogger("state")


def load(path: Path = STATE_FILE, settings: Settings | None = None) -> dict:
    default = {
        "next": {
            "book": (settings.start_book if settings else "John"),
            "chapter": (settings.start_chapter if settings else 1),
        },
        "completed": 0,
        "last_run": None,
        "last_video": None,
        "note": "One chapter a day in canonical order; wraps to Genesis after "
                "Revelation. Started at John per channel plan.",
    }
    if not path.exists():
        log.info("No state file found — starting fresh at %s %s",
                 default["next"]["book"], default["next"]["chapter"])
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["next"]["book"] = normalize_book(data["next"]["book"])
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("state.json unreadable (%s); starting fresh", exc)
        return default


def advance(path: Path, book: str, chapter: int, video_url: str,
            video_id: str) -> dict:
    data = load(path)
    nxt_book, nxt_ch = next_chapter(book, chapter)
    data.update({
        "next": {"book": nxt_book, "chapter": nxt_ch},
        "completed": int(data.get("completed", 0)) + 1,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_video": {"book": book, "chapter": chapter, "id": video_id,
                       "url": video_url},
    })
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    log.info("State advanced → next chapter: %s %d (total completed: %d)",
             nxt_book, nxt_ch, data["completed"])
    return data
