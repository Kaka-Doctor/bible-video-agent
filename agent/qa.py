"""Pre-upload quality gate: a video must EARN its upload.

Before anything is posted to YouTube, the finished video is checked against
the channel guidelines. If ANY check fails, the run refuses to upload, does
NOT advance state, and exits with an error so the failure is clearly visible
in the Actions log. The same chapter is retried on the next scheduled run —
a missing day is always better than a bad video.

Guidelines (all configurable via env — see config.py):
- narration length   >= MIN_SCRIPT_WORDS (default 850 ≈ 6 minutes spoken)
- video duration     within MIN/MAX_VIDEO_MINUTES (default 5.0–9.5; the
                      channel brief is 6–8 minutes)
- structure          at least one "jesus" section, one "application"
                      section and one "verse" section — the channel's
                      signature format
- packaging          non-empty title (≤100 chars), description ≥ 80 chars,
                      existing thumbnail file

A JSON report (output/qa_report.json) is written on every run — pass or
fail — and uploaded as a workflow artifact for inspection.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

log = logging.getLogger("qa")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


# ---------------------------------------------------------------------------
# Check groups
# ---------------------------------------------------------------------------

def check_script(script, settings: Settings) -> list[Check]:
    """The script itself: length + the channel's signature structure."""
    words = script.word_count
    types = [s.type for s in script.sections]
    return [
        Check("script_length", words >= settings.min_script_words,
              f"{words} words of narration (minimum {settings.min_script_words})"),
        Check("has_jesus_section", "jesus" in types,
              f"{types.count('jesus')} seeing-Jesus section(s) — the channel's "
              "signature moment"),
        Check("has_application_section", "application" in types,
              f"{types.count('application')} daily-application section(s)"),
        Check("has_verse_section", "verse" in types,
              f"{types.count('verse')} key-verse section(s)"),
    ]


def check_video(video_path: Path, stats: dict,
                settings: Settings) -> list[Check]:
    """The rendered video: duration inside the channel's brief + real file."""
    duration = float(stats.get("duration", 0.0))
    minutes = duration / 60.0
    size_mb = (video_path.stat().st_size / 1e6) if video_path.exists() else 0.0
    return [
        Check("video_duration_min", minutes >= settings.min_video_minutes,
              f"{minutes:.1f} minutes (minimum {settings.min_video_minutes})"),
        Check("video_duration_max", minutes <= settings.max_video_minutes,
              f"{minutes:.1f} minutes (maximum {settings.max_video_minutes})"),
        Check("video_file", video_path.exists() and size_mb >= 1.0,
              f"{size_mb:.1f} MB — {video_path.name}"),
    ]


def check_packaging(title: str, description: str,
                    thumb_path: Path) -> list[Check]:
    """Upload metadata: title, description and thumbnail are usable."""
    thumb_ok = thumb_path.exists() and thumb_path.stat().st_size >= 20_000
    return [
        Check("title", bool(title.strip()) and len(title) <= 100,
              f"{len(title)} characters"),
        Check("description", len(description.strip()) >= 80,
              f"{len(description.strip())} characters"),
        Check("thumbnail", thumb_ok,
              f"{thumb_path.name} present ({thumb_path.stat().st_size // 1024} KB)"
              if thumb_ok else f"{thumb_path.name} missing or suspiciously small"),
    ]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def log_checks(header: str, checks: list[Check]) -> None:
    log.info("%s: %s", header,
             ", ".join(f"{c.name}={'OK' if c.passed else 'FAIL'}"
                       for c in checks))


def write_report(path: Path, checks: list[Check], **extra) -> bool:
    """Write output/qa_report.json; returns True when everything passed."""
    passed = all(c.passed for c in checks)
    report = {
        "verdict": "PASS" if passed else "FAIL",
        "failed": sum(1 for c in checks if not c.passed),
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                   for c in checks],
        **extra,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        log.warning("Could not write QA report (%s): %s", path, exc)
    return passed
