"""Fetch Bible chapter text from free public APIs.

Primary source:  https://bible-api.com  (no key required)
Fallback source: https://api.getbible.net/v2  (no key required)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger("bible")

# (canonical name, number of chapters, getbible.net book number 1-66)
BOOKS: list[tuple[str, int, int]] = [
    ("Genesis", 50, 1), ("Exodus", 40, 2), ("Leviticus", 27, 3),
    ("Numbers", 36, 4), ("Deuteronomy", 34, 5), ("Joshua", 24, 6),
    ("Judges", 21, 7), ("Ruth", 4, 8), ("1 Samuel", 31, 9),
    ("2 Samuel", 24, 10), ("1 Kings", 22, 11), ("2 Kings", 25, 12),
    ("1 Chronicles", 29, 13), ("2 Chronicles", 36, 14), ("Ezra", 10, 15),
    ("Nehemiah", 13, 16), ("Esther", 10, 17), ("Job", 42, 18),
    ("Psalms", 150, 19), ("Proverbs", 31, 20), ("Ecclesiastes", 12, 21),
    ("Song of Solomon", 8, 22), ("Isaiah", 66, 23), ("Jeremiah", 52, 24),
    ("Lamentations", 5, 25), ("Ezekiel", 48, 26), ("Daniel", 12, 27),
    ("Hosea", 14, 28), ("Joel", 3, 29), ("Amos", 9, 30),
    ("Obadiah", 1, 31), ("Jonah", 4, 32), ("Micah", 7, 33),
    ("Nahum", 3, 34), ("Habakkuk", 3, 35), ("Zephaniah", 3, 36),
    ("Haggai", 2, 37), ("Zechariah", 14, 38), ("Malachi", 4, 39),
    ("Matthew", 28, 40), ("Mark", 16, 41), ("Luke", 24, 42),
    ("John", 21, 43), ("Acts", 28, 44), ("Romans", 16, 45),
    ("1 Corinthians", 16, 46), ("2 Corinthians", 13, 47),
    ("Galatians", 6, 48), ("Ephesians", 6, 49), ("Philippians", 4, 50),
    ("Colossians", 4, 51), ("1 Thessalonians", 5, 52),
    ("2 Thessalonians", 3, 53), ("1 Timothy", 6, 54), ("2 Timothy", 4, 55),
    ("Titus", 3, 56), ("Philemon", 1, 57), ("Hebrews", 13, 58),
    ("James", 5, 59), ("1 Peter", 5, 60), ("2 Peter", 3, 61),
    ("1 John", 5, 62), ("2 John", 1, 63), ("3 John", 1, 64),
    ("Jude", 1, 65), ("Revelation", 22, 66),
]

BOOK_ALIASES = {
    "psalm": "Psalms", "ps": "Psalms", "psalmes": "Psalms",
    "song": "Song of Solomon", "songs": "Song of Solomon",
    "song of songs": "Song of Solomon", "sos": "Song of Solomon",
    "canticles": "Song of Solomon",
    "genesis": "Genesis", "gen": "Genesis",
    "rev": "Revelation", "revelations": "Revelation", "apocalypse": "Revelation",
}

TIMEOUT = 30


@dataclass
class Verse:
    number: int
    text: str


@dataclass
class Chapter:
    book: str
    chapter: int
    translation: str
    verses: list[Verse] = field(default_factory=list)

    @property
    def reference(self) -> str:
        return f"{self.book} {self.chapter}"

    def verse_text(self, numbers: list[int]) -> str:
        """Exact text of one or more consecutive verses, joined."""
        parts = [v.text.strip() for v in self.verses if v.number in numbers]
        return " ".join(parts)

    def full_text(self) -> str:
        return "\n".join(f"{v.number}. {v.text.strip()}" for v in self.verses)


def normalize_book(name: str) -> str:
    key = name.strip().lower()
    key = BOOK_ALIASES.get(key, key).lower()  # alias, then keep lowercase:
    # a found alias is title-case, so compare case-insensitively both ways
    # (bug symptom: "Genesis"/"Revelation" were rejected after alias lookup).
    for canonical, _chapters, _nr in BOOKS:
        if canonical.lower() == key:
            return canonical
    # partial match fallback
    for canonical, _chapters, _nr in BOOKS:
        if canonical.lower().startswith(key) and key:
            return canonical
    raise ValueError(f"Unknown Bible book: {name!r}")


def chapter_count(book: str) -> int:
    for canonical, chapters, _nr in BOOKS:
        if canonical == book:
            return chapters
    raise ValueError(f"Unknown book {book!r}")


def _book_number(book: str) -> int:
    for canonical, _chapters, nr in BOOKS:
        if canonical == book:
            return nr
    raise ValueError(f"Unknown book {book!r}")


def next_chapter(book: str, chapter: int) -> tuple[str, int]:
    """Next chapter in canonical order; wraps Revelation 22 -> Genesis 1."""
    idx = next(
        i for i, (name, _c, _n) in enumerate(BOOKS) if name == book
    )
    name, chapters, _ = BOOKS[idx]
    if chapter < chapters:
        return name, chapter + 1
    if idx + 1 < len(BOOKS):
        nxt, _c, _n = BOOKS[idx + 1]
        return nxt, 1
    return "Genesis", 1


def _fetch_bible_api(book: str, chapter: int, translation: str) -> Chapter:
    ref = f"{book} {chapter}".replace(" ", "+")
    url = f"https://bible-api.com/{ref}"
    r = requests.get(url, params={"translation": translation}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    verses = [Verse(int(v["verse"]), v["text"].strip()) for v in data["verses"]]
    if not verses:
        raise ValueError("empty chapter")
    return Chapter(book=book, chapter=chapter, translation=translation, verses=verses)


def _fetch_getbible(book: str, chapter: int, translation: str) -> Chapter:
    nr = _book_number(book)
    url = f"https://api.getbible.net/v2/{translation}/{nr}/{chapter}.json"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    verses = [Verse(int(v["verse"]), v["text"].strip()) for v in data["verses"]]
    if not verses:
        raise ValueError("empty chapter")
    return Chapter(book=book, chapter=chapter, translation=translation, verses=verses)


def fetch_chapter(book: str, chapter: int, translation: str = "kjv") -> Chapter:
    """Fetch a chapter with retries and a fallback source."""
    book = normalize_book(book)
    total = chapter_count(book)
    if not 1 <= chapter <= total:
        raise ValueError(f"{book} has {total} chapters; got {chapter}")

    errors: list[str] = []
    for attempt in range(3):
        for fetcher in (_fetch_bible_api, _fetch_getbible):
            try:
                ch = fetcher(book, chapter, translation)
                log.info(
                    "Fetched %s %d (%s): %d verses",
                    book, chapter, translation, len(ch.verses),
                )
                return ch
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fetcher.__name__}: {exc}")
                log.warning("Bible fetch failed (%s), trying next source", exc)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {book} {chapter}: {errors[-1]}")
