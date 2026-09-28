"""Generate the daily video script.

Priority:
1. --script-file / SCRIPT_FILE  (fixed JSON, used for testing)
2. Google Gemini (free tier key)  -- preferred
3. Any OpenAI-compatible API      -- optional
4. Built-in template              -- last-resort fallback (no key set)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from .bible import Chapter
from .config import Settings

log = logging.getLogger("scriptgen")

VALID_TYPES = {"intro", "context", "verse", "explanation", "jesus", "application", "outro"}

SCHEMA_HINT = """{
  "hook": "spoken first line that draws the viewer in (15-25 words)",
  "thumbnail_hook": "3-6 punchy words for the thumbnail image",
  "description": "2-3 sentence summary of this episode for YouTube (no hashtags)",
  "sections": [
    {"type": "intro",       "title": "Welcome",                  "narration": "...", "on_screen": ["short phrase", "short phrase"]},
    {"type": "context",     "title": "Where We Are in the Story", "narration": "...", "on_screen": ["...", "..."]},
    {"type": "verse",       "title": "Key Verse",                 "verse_numbers": [1], "narration": "...", "on_screen": []},
    {"type": "explanation", "title": "What This Chapter Says",    "narration": "...", "on_screen": ["...", "...", "..."]},
    {"type": "verse",       "title": "Another Key Verse",         "verse_numbers": [14], "narration": "...", "on_screen": []},
    {"type": "jesus",       "title": "Seeing Jesus",              "narration": "...", "on_screen": ["...", "..."]},
    {"type": "application", "title": "Living It Today",           "narration": "...", "on_screen": ["point one", "point two", "point three"]},
    {"type": "outro",       "title": "Until Tomorrow",            "narration": "...", "on_screen": []}
  ]
}"""


def build_prompt(chapter: Chapter, settings: Settings) -> str:
    return f"""You are a gifted, warm Bible teacher writing the script for a daily devotional YouTube video.

TODAY'S PASSAGE: {chapter.book} chapter {chapter.chapter} — {chapter.translation.upper()}
FULL CHAPTER TEXT:
{chapter.full_text()}

Write the script (~{settings.target_words} words of total narration, about 6-8 minutes spoken).
Structure and spirit of the video:
1. HOOK — one compelling spoken line that makes a viewer want to stay.
2. CONTEXT — where this chapter sits in the story of Scripture: author, audience, era, and what came just before (keep it brief and certain; avoid speculative dates).
3. CHAPTER WALK-THROUGH — walk through the flow of the chapter, pausing on 2-4 KEY VERSES. For each key verse add a "verse" section and put the verse number(s) in "verse_numbers" — the video will display the exact KJV text automatically. Your narration around each verse should explain it plainly.
4. SEEING JESUS — the signature moment of this channel. Reveal where Christ is present or foreshadowed in THIS chapter: a Christophany (like the Angel of the LORD), a prophecy, a type or shadow (the Passover lamb, the bronze serpent, the tabernacle), a divine title, or a New Testament fulfillment. If the chapter seems far from Jesus (genealogies, census lists, ritual laws), trace the honest thread that leads to Him — for example a genealogy that carries the Messianic line, or sacrifices that foreshadow the once-for-all sacrifice. NEVER invent or stretch beyond what Scripture supports.
5. LIVING IT TODAY — exactly 3 concrete, practical applications for ordinary daily life (work, family, money, anxiety, integrity, prayer, forgiveness). Make them specific enough to do today, not vague platitudes.
6. OUTRO — a warm one-line blessing, then invite the viewer to subscribe and join tomorrow for the next chapter.

HARD RULES:
- "narration" is read aloud by a neural voice: plain, speakable English. No markdown, no stage directions, no emojis, no parentheses. Sentences short enough to say in one breath.
- When narration quotes Scripture, quote it EXACTLY as it appears in the chapter text above.
- "on_screen" entries: 2-4 ultra-short phrases (max ~7 words each), title case, no ending punctuation. The application section must have exactly 3.
- "verse_numbers" must be valid verse numbers from the chapter above. Verse slides display the exact text automatically, so keep narration there as explanation, not re-reading.
- "description": 2-3 honest sentences summarizing this episode. No hashtags, no links.

Return ONLY valid JSON matching exactly this shape:
{SCHEMA_HINT}"""


# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, settings: Settings) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    headers = {
        "x-goog-api-key": settings.gemini_api_key,
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.75,
            "maxOutputTokens": 16384,
        },
    }
    if "2.5" in settings.gemini_model or "3" in settings.gemini_model:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 1024}

    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=180)
            if r.status_code == 400 and "thinkingConfig" in json.dumps(body):
                # Older models reject thinkingConfig — retry without it.
                body["generationConfig"].pop("thinkingConfig", None)
                continue
            r.raise_for_status()
            data = r.json()
            cand = data["candidates"][0]
            finish = cand.get("finishReason", "")
            text = "".join(
                p.get("text", "") for p in cand["content"]["parts"]
            )
            if not text.strip():
                raise ValueError(f"empty completion (finishReason={finish})")
            if finish == "MAX_TOKENS":
                log.warning("Gemini hit MAX_TOKENS; output may be truncated.")
            return text
        except requests.RequestException as exc:
            log.warning("Gemini attempt %d failed: %s", attempt + 1, exc)
    raise RuntimeError("Gemini failed after 3 attempts")


def _call_openai_compat(prompt: str, settings: Settings) -> str:
    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.openai_model,
        "temperature": 0.75,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are a warm Bible teacher. "
             "Always answer with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
    }
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=180)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except requests.RequestException as exc:
            log.warning("OpenAI-compat attempt %d failed: %s", attempt + 1, exc)
    raise RuntimeError("OpenAI-compatible API failed after 3 attempts")


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unbalanced JSON")


@dataclass
class Section:
    type: str
    title: str
    narration: str
    on_screen: list[str] = field(default_factory=list)
    verse_numbers: list[int] = field(default_factory=list)

    @property
    def verse_reference(self) -> str:
        return ""


@dataclass
class Script:
    hook: str = ""
    thumbnail_hook: str = ""
    description: str = ""
    sections: list[Section] = field(default_factory=list)
    source: str = "unknown"

    @property
    def word_count(self) -> int:
        return sum(len(s.narration.split()) for s in self.sections) + len(self.hook.split())

    def validate(self, chapter: Chapter) -> None:
        valid_numbers = {v.number for v in chapter.verses}
        cleaned: list[Section] = []
        for sec in self.sections:
            sec.type = str(sec.type).lower().strip()
            if sec.type not in VALID_TYPES:
                sec.type = "explanation"
            sec.title = (sec.title or "").strip()[:80]
            sec.narration = (sec.narration or "").strip()
            sec.on_screen = [str(p).strip()[:60] for p in sec.on_screen if str(p).strip()][:4]
            if sec.type == "verse":
                sec.verse_numbers = [int(n) for n in sec.verse_numbers
                                     if int(n) in valid_numbers][:3]
                if not sec.verse_numbers:
                    log.warning("Dropping verse section with invalid numbers: %s", sec.title)
                    continue
            if sec.narration:
                cleaned.append(sec)
        if not cleaned:
            raise ValueError("script has no usable sections")
        self.sections = cleaned


def _parse_script(raw: str, chapter: Chapter, source: str) -> Script:
    data = _extract_json(raw)
    sections = [
        Section(
            type=s.get("type", "explanation"),
            title=s.get("title", ""),
            narration=s.get("narration", ""),
            on_screen=s.get("on_screen", []) or [],
            verse_numbers=s.get("verse_numbers", []) or [],
        )
        for s in data.get("sections", [])
    ]
    script = Script(
        hook=data.get("hook", ""),
        thumbnail_hook=data.get("thumbnail_hook", ""),
        description=data.get("description", ""),
        sections=sections,
        source=source,
    )
    script.validate(chapter)
    return script


# ---------------------------------------------------------------------------
# Template fallback (no API key configured)
# ---------------------------------------------------------------------------

def _template_script(chapter: Chapter) -> Script:
    first = chapter.verses[0]
    mid = chapter.verses[len(chapter.verses) // 2]
    book2, ch2 = None, None
    from .bible import next_chapter  # local import to avoid cycle at module load
    book2, ch2 = next_chapter(chapter.book, chapter.chapter)

    sections = [
        Section("intro", "Welcome",
                f"Today we open {chapter.book} chapter {chapter.chapter}. "
                "Before we read a single word, take a breath and ask God to "
                "speak to you through this passage.",
                [f"{chapter.book} {chapter.chapter}", "A daily encounter with Scripture"]),
        Section("context", "Where We Are",
                f"{chapter.book} chapter {chapter.chapter} is one of the "
                "building blocks of the story of redemption. Every chapter of "
                "the Bible, including this one, fits into the larger story "
                "that runs from creation, through the fall, to the cross and "
                "the empty tomb. Keep that big story in mind as we read.",
                ["One chapter a day", "The whole story of Scripture", "Read with expectation"]),
        Section("verse", "The Opening Verse", "", [], [first.number]),
        Section("explanation", "What This Chapter Says",
                f"In this chapter, Scripture speaks to who God is and how He "
                "deals with His people. As you listen to the words, notice "
                "the tone: is God giving a promise, giving a warning, or "
                "revealing His character? Every page of the Bible is God "
                "making Himself known to ordinary people like us.",
                ["Listen for God's voice", "Promise, warning, or revelation", "God makes Himself known"]),
        Section("verse", "A Verse from the Middle", "", [], [mid.number]),
        Section("jesus", "Seeing Jesus",
                "Jesus said that the Scriptures testify of Him. In this "
                "chapter, look for the thread that leads to Christ: a promise "
                "that points forward, a picture of grace that echoes the "
                "gospel, or a need that only Jesus can meet. The whole Bible "
                "is one story, and the hero of that story is Jesus.",
                ["The Scriptures testify of Jesus", "One story, one Hero", "Look for the thread"]),
        Section("application", "Living It Today",
                "Here is how to carry this chapter into your day. First, read "
                "the chapter again slowly, and let one verse stand out to you. "
                "Second, turn that verse into one sentence you can pray "
                "before you start your work. Third, do one small act of "
                "obedience before the day ends, so the Word becomes flesh in "
                "your ordinary life.",
                ["Read it again slowly", "Pray one verse", "Obey in one small act"]),
        Section("outro", "Until Tomorrow",
                f"May the Lord bless you and keep you today. Tomorrow we "
                f"continue with {book2} chapter {ch2}. Subscribe and join us "
                "for the next chapter of the greatest story ever told.",
                []),
    ]
    narration_v1 = f"We begin with the opening words: {chapter.verse_text([first.number])}"
    narration_v2 = f"And from the middle of the chapter: {chapter.verse_text([mid.number])}"
    sections[2].narration = narration_v1
    sections[4].narration = narration_v2
    script = Script(
        hook=f"Could one ordinary chapter of the Bible change your day? "
             f"Today, {chapter.book} chapter {chapter.chapter}.",
        thumbnail_hook=f"{chapter.book} {chapter.chapter}",
        description=f"A daily devotional journey through {chapter.book} chapter "
                    f"{chapter.chapter}: what it says, where Jesus is in it, and how to "
                    "live it today. New chapter every day.",
        sections=sections,
        source="template",
    )
    script.validate(chapter)
    return script


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_script_file(path: str, chapter: Chapter) -> Script:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    script = _parse_script(raw, chapter, source=f"file:{path}")
    log.info("Loaded script from %s", path)
    return script


def generate_script(chapter: Chapter, settings: Settings) -> Script:
    if settings.gemini_api_key:
        prompt = build_prompt(chapter, settings)
        raw = _call_gemini(prompt, settings)
        try:
            script = _parse_script(raw, chapter, source=f"gemini:{settings.gemini_model}")
            log.info("Script generated with Gemini (%d words)", script.word_count)
            return script
        except Exception as exc:  # noqa: BLE001
            log.error("Gemini returned unparseable script: %s", exc)
    elif settings.openai_api_key:
        prompt = build_prompt(chapter, settings)
        raw = _call_openai_compat(prompt, settings)
        try:
            script = _parse_script(raw, chapter, source=f"openai:{settings.openai_model}")
            log.info("Script generated with OpenAI-compatible API (%d words)", script.word_count)
            return script
        except Exception as exc:  # noqa: BLE001
            log.error("OpenAI-compatible API returned unparseable script: %s", exc)
    else:
        log.warning("No AI key configured (set GEMINI_API_KEY) — using basic template script.")
    if settings.gemini_api_key or settings.openai_api_key:
        log.warning("Falling back to template script after LLM failure.")
    return _template_script(chapter)
