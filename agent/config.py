"""Central configuration for the Bible video agent.

Everything is driven by environment variables with sensible defaults so the
same code runs locally (for testing) and inside GitHub Actions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"
OUTPUT_DIR = ROOT / "output"
WORK_DIR = OUTPUT_DIR / "work"
STATE_FILE = ROOT / "state.json"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get(key: str, default: str = "") -> str:
    """Env lookup where an unset OR empty value falls back to the default.

    Protects against CI systems that export variables with empty values
    (e.g. GitHub Actions `${{ vars.X }}` when the variable is not defined).
    """
    value = os.environ.get(key)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    # --- Content -----------------------------------------------------------
    translation: str = "kjv"          # bible-api.com translation id
    style: str = "royal_gold"         # slide theme
    target_words: int = 1000          # ~6-8 minutes of narration
    voice: str = "en-US-JennyNeural"  # edge-tts neural voice
    tts_rate: str = "-4%"             # slightly slower, devotional pace
    ken_burns: bool = True            # slow zoom motion on slides

    # --- Branding ----------------------------------------------------------
    channel_name: str = "Biblia Tafsiri Mbalimbali"
    channel_handle: str = "@BIBLIATAFSIRIMBALIMBALI"
    channel_url: str = "https://www.youtube.com/@BIBLIATAFSIRIMBALIMBALI"
    title_template: str = (
        "Summary of the book of {book} - Chapter {chapter} "
        "|| Biblia Tafsiri Mbalimbali"
    )

    # --- AI script writer ----------------------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.7-flash"
    gemini_fallback_models: list[str] = field(
        default_factory=lambda: ["gemini-3.8-flash", "gemini-flash-latest",
                                 "gemini-3.6-flash", "gemini-3.5-flash",
                                 "gemini-3.1-flash-lite"])
    # Storm resilience: how many total script-generation rounds to attempt
    # when the script QA fails (e.g. a Gemini 503 storm leaves only the short
    # template), and how long to wait between rounds for the storm to pass.
    script_retry_rounds: int = 3
    storm_wait_seconds: int = 900
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # --- YouTube -------------------------------------------------------------
    yt_client_id: str = ""
    yt_client_secret: str = ""
    yt_refresh_token: str = ""
    yt_privacy: str = "public"
    yt_category_id: str = "27"  # Education

    # --- Comment replies ------------------------------------------------------
    max_comment_replies: int = 10    # per run; 4 runs/day keeps quota safe
    comment_max_age_days: int = 90   # don't dig up ancient threads

    # --- Quality gate (pre-upload checks) --------------------------------------
    min_script_words: int = 850      # narration words; ~6 minutes spoken
    min_video_minutes: float = 5.0   # final video must be at least this long
    max_video_minutes: float = 9.5   # and never longer (channel brief: 6-8)
    force_upload: bool = False       # bypass the once-per-day guard

    # --- Video ---------------------------------------------------------------
    width: int = 1920
    height: int = 1080
    fps: int = 30

    # --- Run overrides (also settable via CLI) -------------------------------
    book_override: str = ""
    chapter_override: int = 0
    script_file: str = ""
    dry_run: bool = False
    keep_state: bool = False

    # Where the run happens (for logging)
    start_book: str = "John"
    start_chapter: int = 1

    extra_tags: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Settings":
        get = _get
        return cls(
            translation=get("BIBLE_TRANSLATION", "kjv").lower(),
            style=get("VIDEO_STYLE", "royal_gold"),
            target_words=int(get("TARGET_WORDS", "1000")),
            voice=get("VOICE", "en-US-JennyNeural"),
            tts_rate=get("TTS_RATE", "-4%"),
            ken_burns=_bool(get("KEN_BURNS"), True),
            channel_name=get("CHANNEL_NAME", "Biblia Tafsiri Mbalimbali"),
            channel_handle=get("CHANNEL_HANDLE", "@BIBLIATAFSIRIMBALIMBALI"),
            channel_url=get(
                "CHANNEL_URL",
                "https://www.youtube.com/@BIBLIATAFSIRIMBALIMBALI",
            ),
            title_template=get(
                "TITLE_TEMPLATE",
                "Summary of the book of {book} - Chapter {chapter} "
                "|| Biblia Tafsiri Mbalimbali",
            ),
            gemini_api_key=get("GEMINI_API_KEY", ""),
            gemini_model=get("GEMINI_MODEL", "gemini-3.7-flash"),
            gemini_fallback_models=[
                m.strip()
                for m in get("GEMINI_FALLBACK_MODELS",
                             "gemini-3.8-flash,gemini-flash-latest,"
                             "gemini-3.6-flash,gemini-3.5-flash,"
                             "gemini-3.1-flash-lite").split(",")
                if m.strip()
            ],
            script_retry_rounds=int(get("SCRIPT_RETRY_ROUNDS", "3") or 3),
            storm_wait_seconds=int(get("STORM_WAIT_SECONDS", "900") or 900),
            openai_api_key=get("OPENAI_API_KEY", ""),
            openai_base_url=get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_model=get("OPENAI_MODEL", "gpt-4o-mini"),
            yt_client_id=get("YT_CLIENT_ID", ""),
            yt_client_secret=get("YT_CLIENT_SECRET", ""),
            yt_refresh_token=get("YT_REFRESH_TOKEN", ""),
            yt_privacy=get("YT_PRIVACY", "public"),
            yt_category_id=get("YT_CATEGORY_ID", "27"),
            max_comment_replies=int(get("MAX_COMMENT_REPLIES", "10") or 10),
            comment_max_age_days=int(get("COMMENT_MAX_AGE_DAYS", "90") or 90),
            min_script_words=int(get("MIN_SCRIPT_WORDS", "850") or 850),
            min_video_minutes=float(get("MIN_VIDEO_MINUTES", "5.0") or 5.0),
            max_video_minutes=float(get("MAX_VIDEO_MINUTES", "9.5") or 9.5),
            force_upload=_bool(get("FORCE_UPLOAD"), False),
            book_override=get("BOOK_OVERRIDE", "").strip(),
            chapter_override=int(get("CHAPTER_OVERRIDE", "0") or 0),
            script_file=get("SCRIPT_FILE", "").strip(),
            dry_run=_bool(get("DRY_RUN"), False),
            keep_state=_bool(get("KEEP_STATE"), False),
            start_book=get("START_BOOK", "John"),
            start_chapter=int(get("START_CHAPTER", "1") or 1),
            extra_tags=[
                t.strip()
                for t in get("EXTRA_TAGS", "").split(",")
                if t.strip()
            ],
        )

    def video_title(self, book: str, chapter: int) -> str:
        return self.title_template.format(book=book, chapter=chapter)

    @property
    def has_youtube_credentials(self) -> bool:
        return bool(
            self.yt_client_id and self.yt_client_secret and self.yt_refresh_token
        )
