# Bible Video Agent — one chapter a day, auto-posted to YouTube

An autonomous agent that **every day** produces a complete YouTube video for
[Biblia Tafsiri Mbalimbali](https://www.youtube.com/@BIBLIATAFSIRIMBALIMBALI):

> **Summary of the book of John - Chapter 1 || Biblia Tafsiri Mbalimbali**

Each video (6–8 min, 1080p):

1. **Explains the chapter** — context, flow, key verses (KJV)
2. **Shows Jesus in the chapter** — Christophanies, prophecies, types & shadows
3. **Applies it to daily life** — 3 concrete, practical takeaways

It runs itself on **GitHub Actions** (free), writes the script with **Google
Gemini** (free tier), narrates with a **neural voice** (free), renders the
video with **Pillow + FFmpeg** (free), and uploads to **YouTube** with the
official API — going live around **12:00 East Africa Time** daily.

```
state.json ──▶ Bible text (bible-api.com, KJV)
                    │
                    ▼
        Gemini writes the script (JSON)
                    │
                    ▼
   Royal-Gold slides (Pillow)  +  Narration (edge-tts)
                    │                          │
                    └────────┬─────────────────┘
                             ▼
              FFmpeg: Ken Burns motion → 1080p MP4
                             │
                             ▼
              YouTube Data API → upload + thumbnail
                             │
                             ▼
                state.json advances (committed back)
```

> **Why not Google Opal?** Opal has no public API, so it cannot be automated.
> This pipeline achieves the same goal — a good-quality daily video — with
> fully scriptable, zero-cost tools.

---

## What you must provide (one-time, ~20 minutes)

You need exactly **two things**. Your YouTube password is **never** shared
with anyone — access is granted through Google's official OAuth flow.

| # | What | Where it goes | Cost |
|---|------|---------------|------|
| 1 | Gemini API key | GitHub secret `GEMINI_API_KEY` | free |
| 2 | YouTube OAuth (Client ID + Secret + Refresh Token) | GitHub secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | free |

---

### Step 1 — Gemini API key (the script writer)

1. Go to **https://aistudio.google.com** and sign in with any Google account.
2. Click **Get API key** → **Create API key** (no credit card needed).
3. Copy the key (starts with `AIza…` or the newer `AQ.` format).
4. In this repo on GitHub: **Settings → Secrets and variables → Actions →
   New repository secret**
   - Name: `GEMINI_API_KEY`
   - Value: paste the key

Free tier allows ~1,500 requests/day — this agent uses **1 per day**.
(Without this key the agent still runs, but scripts fall back to a basic
template — set the key for real quality.)

### Step 2 — Google Cloud project + OAuth client (the uploader)

1. Go to **https://console.cloud.google.com** → sign in with the Google
   account **that owns your YouTube channel**.
2. Create a project (any name, e.g. `bible-video-agent`).
3. **APIs & Services → Library → search "YouTube Data API v3" → Enable.**
4. **APIs & Services → OAuth consent screen**:
   - User type: **External** → Create
   - Fill the required fields (app name + your email).
   - Add yourself as a **test user** (your email).
   - Click **Publish app** (so your refresh token does not expire after
     7 days — see Troubleshooting).
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application** (or Desktop app — both work)
   - If you chose **Web application**, under *Authorized redirect URIs* add
     exactly: `http://localhost:8765`
   - Copy the **Client ID** and **Client secret**.
6. Add them as GitHub repo secrets:
   - `YT_CLIENT_ID` and `YT_CLIENT_SECRET`

### Step 3 — Refresh token (this is how the agent gets channel access)

On **your own computer** (needs Python 3.8+ only):

```bash
python3 scripts/get_refresh_token.py
# paste the Client ID and Client Secret when asked
```

Your browser opens → **sign in with the channel's Google account** → click
**Allow**. The terminal prints a refresh token (also saved to
`refresh_token.txt`). Add it as the GitHub secret:

- `YT_REFRESH_TOKEN`

That's the whole "access grant": Google issued a token that lets this repo's
workflow upload videos **to your channel only** — it cannot read your email,
change your password, or touch anything else, and you can revoke it any time
at https://myaccount.google.com/permissions.

### Step 4 — Test it (before the first scheduled run)

On GitHub: **Actions → Daily Bible Video → Run workflow**:
- leave inputs blank for "next chapter" (John 1), or set `book`/`chapter`
- tick **Dry run — render but do not upload** for a safe first test

Watch the run (~10–15 min), then download the video from the run's
**Artifacts**. Happy with it? Run again without the dry-run tick — the video
goes live on your channel and `state.json` advances to the next chapter.

### Step 5 — Let it run

The schedule is `15 8 * * *` UTC = **11:15 EAT** → the video is live before
**12:00 EAT** every day. After each successful upload the workflow commits
the updated `state.json`, so tomorrow's run picks up the next chapter
(John 1 → John 2 → … → Revelation 22 → Genesis 1 → … all 1,189 chapters).

The **Reply to Comments** workflow runs **every 6 hours** (03:40, 09:40,
15:40, 21:40 EAT) — see the next section.

---

## One video per day — guaranteed

Exactly **one** video goes out per EAT calendar day, no matter how many
triggers fire: delayed cron runs, manual "Run workflow" clicks, re-runs,
or the backup cron slot (08:45 UTC, which catches GitHub's occasional
multi-hour cron delays). After a successful upload the workflow commits
`last_post_date` into `state.json`; every later trigger the same day sees
the once-per-day guard in `agent/main.py` and exits cleanly without
posting. Need an exception (e.g. re-posting after deleting a bad video)?
Run the workflow with the **`force`** input ticked, or locally:
`python -m agent.main --force`.

## Pre-upload quality gate

A video must **earn** its upload. Before anything is posted, the agent
checks it against the channel guidelines (`agent/qa.py`) and refuses to
upload — leaving state untouched so the chapter retries the next day — if
ANY check fails:

| Check | Requirement |
|-------|-------------|
| `script_length` | ≥ `MIN_SCRIPT_WORDS` (850) words of narration ≈ 6 minutes |
| `has_jesus_section` | the channel's signature "Seeing Jesus" section present |
| `has_application_section` | practical daily-life application present |
| `has_verse_section` | at least one key-verse section |
| `video_duration_min/max` | final video between `MIN_VIDEO_MINUTES` (5.0) and `MAX_VIDEO_MINUTES` (9.5) |
| `title` / `description` / `thumbnail` | non-empty, sane sizes |

Short Gemini drafts are not accepted either: the script writer regenerates
them up to 3 times with an explicit length demand before the gate sees
them. A full JSON report is written to `output/qa_report.json` and attached
to every workflow run as an artifact — check it any time a day is skipped.

## Epic thumbnails

Every video gets a dedicated high-impact YouTube thumbnail (not a scaled-down
slide): dramatic navy backdrop with god-rays and a **glowing cross**, a
**massive metallic-gold book name** (numeric prefixes like "1" in
"1 Corinthians" are split off so the name itself stays huge), a gold
**CHAPTER N** badge, and a punchy white hook line. The whole text stack is
dynamically centered and auto-sized to the vertical budget, so no book name
or hook length can ever overflow the frame — verified with box-measurement
QA and five VLM design reviews. The hook comes from the script's
`thumbnail_hook`; hooks are trimmed to the 4 most meaningful words and
remain readable at mobile-feed size.

## Play Store app link in every description

Every uploaded description ends with:

> Download Our App from PlayStore with this link:
> https://play.google.com/store/apps/details?id=com.biblia.tafsiri.mbalimbali

Already-live videos get the footer too: run the **Retrofit Live Videos**
workflow (`.github/workflows/update_live_videos.yml`, manual dispatch). It
re-renders the epic thumbnail and appends the link for every agent video on
the channel — idempotent, safe to re-run, with `dry_run` and `video_id`
knobs for previews/single-video updates.

---

## Comment replies — warm tone, biblical wisdom

Every 6 hours the agent checks all comments on all of the channel's videos
and replies to the new ones **in the commenter's own language**
(English, Swahili, or mixed). Each reply is written fresh by Gemini:

- **Warm, humble, pastoral tone** — like a gracious teacher writing to a friend.
- **One short piece of biblical wisdom** — a fitting verse reference or a
  faithfully quoted Scripture line (KJV wording welcome).
- **1–3 sentences, ≤ 60 words** — never walls of text, never spammy.

Safety rails (so the channel never embarrasses itself):

- Never replies to **itself** (pinned comments, own replies).
- Never replies **twice** — already-replied comments are detected live from
  the thread's replies AND the committed `comments_state.json`.
- Never **argues**: hostile, mocking, or spam comments are answered with
  silence (Proverbs 26:4) — the model is instructed to skip them.
- Never **invents** personal stories or credentials, no links, no hashtags.
- At most **10 replies per run** (configurable) and stops instantly on quota
  errors. Comment threads older than 90 days are left in peace.
- If Gemini is down, the run **stays silent** and retries in 6 hours —
  no generic copy-paste replies, ever.

Manual control:

- Draft without posting: **Actions → Reply to Comments → Run workflow →
  tick `dry_run`** (lists the comments and shows the drafted replies in the log).
- Burst mode: same screen, set `max_replies` (e.g. `25`) for one bigger sweep.

| Variable | Default | Meaning |
|----------|---------|---------|
| `MAX_COMMENT_REPLIES` | `10` | Max replies per 6-hour run |
| `COMMENT_MAX_AGE_DAYS` | `90` | Ignore comment threads older than this |

---

## Customization

All via **Settings → Secrets and variables → Actions → Variables** (or the
defaults in `agent/config.py`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `VOICE` | `en-US-JennyNeural` | Any edge-tts voice (e.g. `en-US-GuyNeural` male, `en-GB-SoniaNeural` British) |
| `YT_PRIVACY` | `public` | `public` / `unlisted` / `private` |
| `GEMINI_MODEL` | `gemini-3.7-flash` | Any Gemini model (verified working) |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.8-flash,gemini-flash-latest,gemini-3.6-flash` | Backup models if the primary is overloaded (503) — probed & verified with this key; `gemini-2.5-flash` returns 404 and must NOT be used |
| `TARGET_WORDS` | `1000` | Script length (~6–8 min) |
| `TTS_RATE` | `-4%` | Narration speed |
| `TITLE_TEMPLATE` | `Summary of the book of {book} - Chapter {chapter} \|\| Biblia Tafsiri Mbalimbali` | Video title format |
| `KEN_BURNS` | `1` | `0` disables slide motion (faster renders) |
| `MAX_COMMENT_REPLIES` | `10` | Comment replies per run (see Comment replies section) |
| `COMMENT_MAX_AGE_DAYS` | `90` | Don't reply to threads older than this |
| `MIN_SCRIPT_WORDS` | `850` | Quality gate: minimum narration words (≈ 6 min) |
| `MIN_VIDEO_MINUTES` | `5.0` | Quality gate: minimum final video length |
| `MAX_VIDEO_MINUTES` | `9.5` | Quality gate: maximum final video length |

Restart-from-scratch: edit `state.json` → `next.book` / `next.chapter`.

## Troubleshooting

- **Upload arrives as *private (locked)** — YouTube locks API uploads from
  *unverified* Google projects to private. Fix: submit the OAuth consent
  screen for **verification** (Google review, a few days, free), or publish
  each video manually in YouTube Studio in the meantime.
- **Refresh token stopped working** — if your consent screen is in *Testing*
  mode, tokens expire after 7 days. Set it to **Production/Publish** and
  re-run `scripts/get_refresh_token.py`, then update the secret.
- **No video posted today** — the quality gate refused it (by design: a
  missing day beats a bad video). Open the day's workflow run → logs, or
  download the run artifact and read `qa_report.json` to see which check
  failed. State was NOT advanced, so the same chapter retries next run.
- **Scheduled run didn't fire at exactly 11:15** — GitHub cron can be delayed
  by minutes or (rarely) hours; a 08:45 UTC backup slot catches the misses,
  and the once-per-day guard makes double-firing impossible.
- **No runs for 60 days** — GitHub auto-disables cron workflows on inactive
  repos. This repo commits `state.json` daily, which keeps it alive. If you
  paused it for 60+ days, just push any commit and re-enable the workflow.
- **Quota** — YouTube grants 10,000 API units/day; one upload ≈ 1,600, one
  comment sweep ≈ 10–520 (10 replies × 50 + listing). Even at full tilt you
  stay far below the ceiling.

## Costs

Everything runs on free tiers: GitHub Actions (public-runner minutes for a
daily 15-min job), Gemini free tier, edge-tts, bible-api.com, FFmpeg.
**Total: $0/month.**

## Security

- All credentials live in **GitHub Secrets** — never in files or commits.
- The YouTube token is upload-only for your channel and revocable anytime
  at https://myaccount.google.com/permissions.
- If you ever shared a GitHub PAT in chat while setting this up, **rotate or
  revoke it** now: https://github.com/settings/tokens — the daily workflow
  does not need it (it uses GitHub's built-in token).

## Repository layout

```
agent/            the agent itself
  main.py         orchestrator — python -m agent.main
  bible.py        chapter text (bible-api.com + getbible.net fallback)
  scriptgen.py    Gemini script writer (+ OpenAI-compatible + template)
  slides.py       Royal-Gold slide designs (Pillow)
  theme.py        palette, fonts, starfield, cross, ornaments
  tts.py          edge-tts narration
  video.py        FFmpeg Ken Burns assembly
  youtube.py      resumable upload + thumbnail + description
  comments.py     comment replies — python -m agent.comments
  qa.py           pre-upload quality gate (guidelines enforcement)
  state.py        next-chapter pointer + once-per-day guard
scripts/get_refresh_token.py   one-time YouTube authorization
examples/john1_script.json     full sample script (used for testing)
fonts/            Cinzel, EB Garamond, Inter (SIL Open Font License)
.github/workflows/daily_video.yml    the daily video schedule
.github/workflows/reply_comments.yml the 6-hourly comment replies
comments_state.json             which comments were already replied to
```
