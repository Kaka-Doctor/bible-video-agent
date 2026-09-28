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

---

## Customization

All via **Settings → Secrets and variables → Actions → Variables** (or the
defaults in `agent/config.py`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `VOICE` | `en-US-JennyNeural` | Any edge-tts voice (e.g. `en-US-GuyNeural` male, `en-GB-SoniaNeural` British) |
| `YT_PRIVACY` | `public` | `public` / `unlisted` / `private` |
| `GEMINI_MODEL` | `gemini-3.7-flash` | Any Gemini model |
| `TARGET_WORDS` | `1050` | Script length (~6–8 min) |
| `TTS_RATE` | `-4%` | Narration speed |
| `TITLE_TEMPLATE` | `Summary of the book of {book} - Chapter {chapter} \|\| Biblia Tafsiri Mbalimbali` | Video title format |
| `KEN_BURNS` | `1` | `0` disables slide motion (faster renders) |

Restart-from-scratch: edit `state.json` → `next.book` / `next.chapter`.

## Troubleshooting

- **Upload arrives as *private (locked)** — YouTube locks API uploads from
  *unverified* Google projects to private. Fix: submit the OAuth consent
  screen for **verification** (Google review, a few days, free), or publish
  each video manually in YouTube Studio in the meantime.
- **Refresh token stopped working** — if your consent screen is in *Testing*
  mode, tokens expire after 7 days. Set it to **Production/Publish** and
  re-run `scripts/get_refresh_token.py`, then update the secret.
- **Scheduled run didn't fire at exactly 11:15** — GitHub cron can be delayed
  by a few minutes at busy times; the video still goes out that morning.
- **No runs for 60 days** — GitHub auto-disables cron workflows on inactive
  repos. This repo commits `state.json` daily, which keeps it alive. If you
  paused it for 60+ days, just push any commit and re-enable the workflow.
- **Quota** — YouTube grants 10,000 API units/day; one upload ≈ 1,600.
  You have room for ~6 uploads/day if you ever want more.

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
  state.py        next-chapter pointer
scripts/get_refresh_token.py   one-time YouTube authorization
examples/john1_script.json     full sample script (used for testing)
fonts/            Cinzel, EB Garamond, Inter (SIL Open Font License)
.github/workflows/daily_video.yml   the daily schedule
```
