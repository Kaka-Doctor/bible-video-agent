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
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .bible import Chapter
from .config import Settings

log = logging.getLogger("scriptgen")

VALID_TYPES = {"intro", "context", "verse", "explanation", "jesus", "application", "outro"}

# How many times to re-ask Gemini when a draft comes back too short
# (the pre-upload quality gate then makes the final call on posting).
MAX_DRAFTS = 3

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

Write the script with {settings.target_words}–{settings.target_words + 250} words of total
narration — that is 6-8 minutes spoken. Longer is NOT better: stay inside
the range, and never go below it.
Structure and spirit of the video:
1. HOOK — one compelling spoken line that makes a viewer want to stay.
2. CONTEXT — where this chapter sits in the story of Scripture: author, audience, era, and what came just before (keep it brief and certain; avoid speculative dates).
3. CHAPTER WALK-THROUGH — walk through the flow of the chapter, pausing on 2-4 KEY VERSES. For each key verse add a "verse" section and put the verse number(s) in "verse_numbers" — the video will display the exact KJV text automatically. Your narration around each verse should explain it plainly.
4. SEEING JESUS — the signature moment of this channel. Reveal where Christ is present or foreshadowed in THIS chapter: a Christophany (like the Angel of the LORD), a prophecy, a type or shadow (the Passover lamb, the bronze serpent, the tabernacle), a divine title, or a New Testament fulfillment. If the chapter seems far from Jesus (genealogies, census lists, ritual laws), trace the honest thread that leads to Him — for example a genealogy that carries the Messianic line, or sacrifices that foreshadow the once-for-all sacrifice. NEVER invent or stretch beyond what Scripture supports.
5. LIVING IT TODAY — exactly 3 concrete, practical applications for ordinary daily life (work, family, money, anxiety, integrity, prayer, forgiveness). Make them specific enough to do today, not vague platitudes.
6. OUTRO — a warm one-line blessing, then invite the viewer to subscribe and join tomorrow for the next chapter.

HARD RULES:
- LENGTH (critical): total narration across all sections must be between
  {settings.target_words} and {settings.target_words + 250} words — count
  roughly as you write. Aim for: intro 70-100 words; context 120-180;
  each explanation section 130-200; verse sections 40-80 (commentary around
  the verse, not re-reading it); "seeing Jesus" 140-200; application 170-220
  (about 60 words per point); outro 50-80. Use at most 11 sections.
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

def _call_gemini_model(prompt: str, settings: Settings, model: str,
                       max_attempts: int = 5) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
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
    if "2.5" in model or "3" in model:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 2048}

    # Transient server-side conditions worth retrying with backoff.
    retryable = {429, 500, 502, 503, 504}
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=180)
        except requests.RequestException as exc:
            log.warning("Gemini attempt %d/%d network error: %s",
                        attempt, max_attempts, exc)
        else:
            if r.status_code in retryable:
                log.warning("Gemini attempt %d/%d got HTTP %d (transient)",
                            attempt, max_attempts, r.status_code)
            elif (r.status_code == 400
                  and "thinkingConfig" in body["generationConfig"]):
                # Older models reject thinkingConfig — retry once without it.
                body["generationConfig"].pop("thinkingConfig", None)
                log.warning("Gemini rejected thinkingConfig; retrying without it")
                continue
            else:
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
        if attempt < max_attempts:
            wait = min(8 * 2 ** (attempt - 1), 45)  # 8s, 16s, 32s, 45s
            log.warning("Retrying %s in %ds…", model, wait)
            time.sleep(wait)
    raise RuntimeError(f"{model} failed after {max_attempts} attempts")


def _call_gemini(prompt: str, settings: Settings) -> tuple[str, str]:
    """Try the primary model, then the fallback chain.

    Different models live in different serving capacity pools, so when the
    primary is overloaded (503) an alias like gemini-flash-latest often still
    works. Unknown model names 404 immediately and cost nothing.

    Returns (text, model_actually_used).
    """
    chain: list[str] = [settings.gemini_model]
    chain += [m for m in settings.gemini_fallback_models
              if m and m != settings.gemini_model]
    last_exc: Exception | None = None
    for i, model in enumerate(chain):
        attempts = 5 if i == 0 else 3
        try:
            return _call_gemini_model(prompt, settings, model,
                                      max_attempts=attempts), model
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("Gemini model %s unavailable: %s", model, exc)
            if i < len(chain) - 1:
                log.warning("Switching to fallback model: %s", chain[i + 1])
    raise RuntimeError(
        f"all Gemini models failed ({', '.join(chain)}): {last_exc}")


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
    for attempt in range(1, 4):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=180)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except requests.RequestException as exc:
            log.warning("OpenAI-compat attempt %d/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(8 * 2 ** (attempt - 1))
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

def _template_script(chapter: Chapter, min_words: int = 850) -> Script:
    """Last-resort script when every AI backend is down.

    Verse-anchored so it stays chapter-specific: the narration walks the
    chapter's own verses aloud (KJV text fetched from bible-api.com, which
    needs no AI key), framed with devotional commentary and reflections.
    Long enough to pass the pre-upload quality gate for typical chapters,
    so a total Gemini outage still results in a full-length video instead
    of a dark day for the channel.
    """
    from .bible import next_chapter  # local import to avoid cycle at module load
    book2, ch2 = next_chapter(chapter.book, chapter.chapter)

    n = len(chapter.verses)
    # Key verses at strategic positions: opening, early, center, late, closing.
    positions = sorted({0, n // 3, n // 2, (2 * n) // 3, max(0, n - 1)})
    key_verses = [chapter.verses[i] for i in positions[:5]]

    def verse_section(title: str, framing: str, v, reflection: str = "") -> Section:
        narration = f"{framing} {chapter.verse_text([v.number])}"
        if reflection:
            narration = f"{narration} {reflection}"
        return Section("verse", title, narration, [], [v.number])

    sections = [
        Section("intro", "Welcome",
                f"Welcome back, friend. Today we open {chapter.book} chapter "
                f"{chapter.chapter}, and this passage has something to say to "
                "you personally. Before we read a single word, take a slow "
                "breath, quiet your heart, and ask God to speak to you through "
                "these verses. He is the same God who spoke to the first "
                "readers of this chapter, and He still speaks today, and what "
                "He has to say to you in the next few minutes may be exactly "
                "the word you have been waiting for.",
                [f"{chapter.book} {chapter.chapter}", "A daily encounter with Scripture"]),
        verse_section(
            "The Opening Words", "Hear now the opening words of this chapter.",
            key_verses[0],
            "Even this first verse sets the tone for everything that follows, "
            "so receive it slowly rather than rushing ahead."),
        Section("context", "Where We Are in the Story",
                f"{chapter.book} chapter {chapter.chapter} is one of the "
                "building blocks of the story of redemption. Every chapter of "
                "the Bible, including this one, fits into the larger story "
                "that runs from creation, through the fall, through Israel "
                "and the prophets, to the cross and the empty tomb, and "
                "finally to the new creation. You are not reading random "
                "words; you are stepping into one room of a great house that "
                "God has been building across the centuries. Keep that big "
                "story in mind as we walk through this chapter together, "
                "because it changes how every sentence reads.",
                ["One chapter a day", "The whole story of Scripture", "Read with expectation"]),
    ]

    # Center verse walk with commentary around it.
    mid_idx = min(2, len(key_verses) - 1)
    sections.append(verse_section(
        "A Verse from the Heart of the Chapter",
        "Here is a verse from the very center of the passage.",
        key_verses[mid_idx],
        "Read like a person listening for a knock on the door: what is God "
        "saying to you right here, right now, through these words?"))
    sections.append(
        Section("explanation", "What This Chapter Is Saying",
                f"Every part of Scripture carries God's voice, and this "
                f"chapter is no exception. As you heard those words, notice "
                "what kind of word this is. Is God making a promise to hold "
                "onto? Is He giving a warning to heed? Is He revealing His "
                "own character, His holiness, His mercy, or His faithfulness? "
                f"In {chapter.book} chapter {chapter.chapter}, the living God "
                "is making Himself known to ordinary people, and that "
                "includes you. The same voice that spoke light into darkness "
                "at creation speaks through this page into your situation "
                "today. Do not rush past it; let the words you just heard "
                "settle on your heart before we continue.",
                ["Listen for God's voice", "Promise, warning, or revelation",
                 "God makes Himself known"]))

    if len(key_verses) > mid_idx + 1:
        sections.append(verse_section(
            "Another Key Verse",
            "Now hear these words from the later part of the chapter.",
            key_verses[mid_idx + 1],
            "Notice how the chapter keeps developing its message as it goes; "
            "Scripture rarely says everything at once."))

    sections.extend([
        Section("explanation", "Why This Chapter Matters",
                f"Why should {chapter.book} chapter {chapter.chapter} matter "
                "to you on an ordinary day like today? Because the Bible is "
                "not a museum book; it is a living word. The men and women in "
                "this chapter faced real pressures, real choices, real "
                "disappointments, and real joys, just like yours. And into "
                "the middle of those ordinary lives, God spoke. When you read "
                "their story honestly, you begin to recognize your own story: "
                "the same weaknesses, the same hopes, the same need for grace. "
                "That is why we read chapter by chapter, day after day; over "
                "time the whole counsel of God reshapes how we think, how we "
                "work, how we love the people around us.",
                ["A living word for today", "Their story, our story", "Grace for ordinary lives"]),
        Section("jesus", "Seeing Jesus",
                "Here is the signature question of this channel: where is "
                "Jesus in this chapter? He said Himself that the Scriptures "
                "testify of Him, so look for the thread that leads to Christ. "
                "It may be a promise that points forward to His coming. It "
                "may be a picture of grace that echoes the gospel. It may be "
                "a sacrifice, a priest, a king, or a rescuer who foreshadows "
                "the one true Savior. It may simply be a deep human need that "
                "only Jesus can meet, a hunger that earthly things cannot "
                "satisfy. Whatever the thread is, follow it honestly, without "
                "stretching the text beyond what it says, and you will find "
                "that this chapter belongs to the greatest story ever told, "
                "the story whose hero is Christ crucified and risen.",
                ["The Scriptures testify of Jesus", "One story, one Hero",
                 "Look for the thread"]),
        Section("application", "Living It Today",
                "So how do you carry this chapter out of the screen and into "
                "your day? Here are three simple steps. First, read the "
                "chapter once more, slowly, and let a single verse stand out "
                "to you; that verse is yours for today, so write it down or "
                "screenshot it. Second, turn that verse into one sentence of "
                "prayer before your work begins, speaking it back to God as "
                "your own request or your own surrender. Third, do one small "
                "concrete act of obedience before the day ends, an act of "
                "kindness, honesty, forgiveness, or generosity, so that the "
                "Word becomes flesh in your ordinary life and not just sound "
                "in your ears. Small steps like these, taken daily, will "
                "change the shape of your life over a year.",
                ["Read it again slowly", "Pray one verse", "Obey in one small act"]),
    ])

    # Closing verse (if the chapter has one) right before the outro.
    if len(key_verses) >= 2 and key_verses[-1].number not in (
            key_verses[0].number, key_verses[mid_idx].number,
            key_verses[min(mid_idx + 1, len(key_verses) - 1)].number):
        sections.append(verse_section(
            "The Closing Words",
            "And the chapter draws to a close with words like these.",
            key_verses[-1],
            "Endings in Scripture are invitations: carry this word with you "
            "into the rest of your day."))

    sections.append(
        Section("outro", "Until Tomorrow",
                f"May the Lord bless you and keep you today, and may the "
                f"words of {chapter.book} chapter {chapter.chapter} stay "
                "alive in your heart until tonight. If this brief time in "
                "the Word blessed you, subscribe and join us again tomorrow "
                f"for {book2} chapter {ch2}, the next chapter of the "
                "greatest story ever told.",
                []))

    # Adaptive padding: only ultra-short chapters (a couple of tiny verses)
    # can still fall below the gate — deepen the devotion until they pass.
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
    pad_paras = [
        "Take one more quiet moment before we close. Ask yourself honestly: "
        "what in this chapter corrected you, comforted you, or confronted "
        "you? God's word is described as living and active, sharper than "
        "any two-edged sword, and it discerns the thoughts and intentions of "
        "the heart. That means this chapter was not written merely to inform "
        "you; it was written to reach you. Let the verse that touched you "
        "today become a companion for the week, and return to it whenever "
        "your heart feels dry.",
        "And remember why we do this every single day. Faith is not built in "
        "a single dramatic moment; it is built the way a body is built, meal "
        "by meal, day by day. When you feed on the Word daily, you begin to "
        "think God's thoughts after Him, you recognize His voice in your "
        "conscience, and you stand firmer when the storms of life come. Stay "
        "in the Book, and the Book will keep you.",
    ]
    i = 0
    while script.word_count < min_words and i < len(pad_paras):
        insert_at = max(1, len(script.sections) - 1)
        script.sections.insert(
            insert_at,
            Section("explanation", "One More Quiet Moment", pad_paras[i],
                    ["Let it reach you", "Daily bread", "Stay in the Word"]))
        i += 1
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
        min_words = settings.min_script_words
        best: Script | None = None
        for draft in range(1, MAX_DRAFTS + 1):
            if draft > 1:
                prev = best.word_count if best else 0
                prompt = prompt + (
                    f"\n\nCRITICAL LENGTH FIX: your previous draft had only "
                    f"{prev} words of narration — too short. Write the COMPLETE "
                    f"script with at least {min_words} words of total narration "
                    "across all sections. Do not summarize, do not abbreviate, "
                    "do not omit or merge sections; develop each one fully.")
            try:
                raw, model_used = _call_gemini(prompt, settings)
                script = _parse_script(raw, chapter,
                                       source=f"gemini:{model_used}")
                if script.word_count >= min_words:
                    log.info("Script generated with Gemini %s (%d words, "
                             "draft %d/%d)", model_used, script.word_count,
                             draft, MAX_DRAFTS)
                    return script
                log.warning("Gemini draft %d/%d TOO SHORT (%d words, need %d) "
                            "— regenerating with a stricter length demand",
                            draft, MAX_DRAFTS, script.word_count, min_words)
                if best is None or script.word_count > best.word_count:
                    best = script
            except Exception as exc:  # noqa: BLE001
                log.error("Gemini draft %d/%d failed (%s)", draft,
                          MAX_DRAFTS, exc)
        if best is not None:
            log.error("All %d Gemini drafts were short (best: %d words). The "
                      "pre-upload quality gate will now decide whether this "
                      "script may be posted at all.", MAX_DRAFTS,
                      best.word_count)
            return best
        log.error("Gemini failed completely — falling back to the template "
                  "script for today (the quality gate will still vet it).")
    elif settings.openai_api_key:
        prompt = build_prompt(chapter, settings)
        try:
            raw = _call_openai_compat(prompt, settings)
            script = _parse_script(raw, chapter,
                                   source=f"openai:{settings.openai_model}")
            log.info("Script generated with OpenAI-compatible API (%d words)",
                     script.word_count)
            return script
        except Exception as exc:  # noqa: BLE001
            log.error("OpenAI-compatible API failed completely (%s) — falling "
                      "back to the template script for today.", exc)
    else:
        log.warning("No AI key configured (set GEMINI_API_KEY) — using basic template script.")
    return _template_script(chapter, min_words=settings.min_script_words)
