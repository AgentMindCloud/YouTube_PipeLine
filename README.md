# yt-pipeline 🎬 → ▶️

**Fully automatic YouTube Shorts factory:** it invents the idea, writes the script,
voices it, paints the visuals, burns karaoke-style captions, mixes music, renders a
1080×1920 video — and uploads it to your channel. With a human approval gate by
default, or `--auto` for true unattended runs.

```
 idea ──▶ script ──▶ voice ──▶ visuals ──▶ captions ──▶ music ──▶ render ──▶ [approve] ──▶ YouTube
  GPT/      GPT/     OpenAI    gpt-image-1  word-level   synth      ffmpeg     human gate    Data API v3
  seeds    seeds    /edge-tts  /Pexels/     karaoke      lofi bgm   Ken Burns  or --auto     resumable
                              local art    ASS subs     (ducked)   + fades
```

Every stage has a **free offline fallback**, so the pipeline runs end-to-end with
**zero API keys** (seed scripts + Microsoft edge-tts neural voice + built-in visual
renderer + synthesized music). Add keys to upgrade quality:

| Stage    | No keys (default)                          | With keys                                          |
|----------|--------------------------------------------|----------------------------------------------------|
| Idea     | curated seed bank (never repeats)          | GPT generates fresh ideas for your niche           |
| Script   | seed bank scripts                          | `gpt-4o-mini` shorts-writer prompt                 |
| Voice    | edge-tts neural voice + **exact word timings** | `gpt-4o-mini-tts` (any OpenAI voice)           |
| Visuals  | built-in renderer (gradients, bokeh, grain)| `gpt-image-1` art → Pexels photos → local fallback |
| Music    | synthesized lofi/ambient (royalty-free)    | same (never a licensing problem)                   |

---

## Quick start (5 minutes)

```bash
pip install -r requirements.txt          # python ≥3.10
sudo apt install ffmpeg                  # or brew install ffmpeg
cp .env.example .env                     # fill in OPENAI_API_KEY (optional but recommended)

python run.py run --no-upload            # one full video, no keys needed
python run.py list                       # see the run
```

Open `output/<run-id>/final.mp4` — then:

```bash
python run.py approve <run-id>                  # human-in-the-loop publish
python run.py run --auto --privacy public       # or unattended
```

### Enable real uploads (YouTube Data API v3)

1. [console.cloud.google.com](https://console.cloud.google.com) → new project →
   **APIs & Services → Library → enable "YouTube Data API v3"**.
2. **Credentials → Create credentials → OAuth client ID → Desktop app** →
   download the JSON and save it as `client_secrets.json` in this folder.
3. `python run.py auth login` — browser opens, authorize, done. Token cached in
   `output/token.json`.

> ⚠️ **Unverified-project rule:** uploads through an unaudited API project are
> automatically locked to **private**. That's fine for testing. For public
> automation, complete Google's *YouTube API Services audit* (or start with
> unlisted + manual review). Details:
> https://developers.google.com/youtube/terms/required-disclosures
>
> Quota: an upload costs **1600 units**; default daily quota is 10 000 ⇒ ~6 uploads/day.
> `upload.daily_upload_limit` in config.yaml is a local safety valve (default 3).

Headless servers / CI (no browser): after `auth login` on your laptop, copy
`client_id`, `client_secret`, `refresh_token` from `output/token.json` into the
`YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN` env vars.

---

## Commands

| Command | What it does |
|---|---|
| `python run.py idea [--count N] [--save]` | generate & rank ideas for your niche |
| `python run.py run` | full pipeline: fresh idea → rendered video → approval gate |
| `python run.py run --idea "topic text"` | pipeline with your own topic |
| `python run.py run --auto` | unattended mode: render **and upload** (cron/CI) |
| `python run.py run --no-upload` | render only |
| `python run.py run --privacy public` | override privacy for this upload |
| `python run.py run --force` | regenerate cached stage artifacts |
| `python run.py run --run-id <id>` | resume/retry a failed run (skips done stages) |
| `python run.py approve <run-id> [--privacy X]` | publish a rendered video |
| `python run.py upload <file> --title T` | upload any existing video |
| `python run.py auth login / status` | OAuth setup / check |
| `python run.py list` / `status <run-id>` | run registry |

Each run is a self-contained folder:

```
output/20260919-104356-…/
├── final.mp4          ← the Short (1080×1920, ≤60 s)
├── thumb.png          ← custom thumbnail (1280×720)
├── metadata.json      ← exact title/description/tags/privacy sent to YouTube
├── status.json        ← stage + state machine (awaiting_approval | uploaded)
├── script.json words.json idea.json durations.json
├── captions.ass       ← karaoke captions (editable! re-render keeps everything else)
├── voice.wav music.wav beats/ segments/
└── upload_result.json ← videoId + URL once published
```

## Automation

* **cron** — `deploy/cron.example` (daily `run --auto`)
* **systemd** — `deploy/ytpipeline.service` + `deploy/ytpipeline.timer`
  (`systemctl enable --now ytpipeline.timer`)
* **GitHub Actions** — copy `deploy/github-action.yml` to `.github/workflows/`,
  add the 4 secrets; zero infrastructure.

## What the output looks like

* 1080×1920 @30 fps, ≤ `video.max_duration` (auto-tempo guard if narration overruns)
* Ken Burns motion on every beat, alternating in/out
* Word-by-word highlighted captions (exact TTS word boundaries when available)
* Channel-handle watermark, big on-screen beat text, SUBSCRIBE CTA card
* Progress bar, fade in/out, loudness-normalized voice (-15 LUFS) over ducked lofi BGM
* Title ≤100 chars, hashtags, tags, category, madeForKids=False, optional playlist + thumbnail

## Configuration

Everything in `config.yaml`: channel identity & tone, brand colors, caption style,
voice, visual provider, music style/bpm, upload privacy/playlist/limits, schedule.
Secrets live in `.env` only. See comments in both files.

**Cost per Short (rough, with OpenAI):** script ≈ $0.001 · voice ≈ $0.01 ·
6× gpt-image-1 ≈ $0.35 → **≈ $0.36**. With local visuals ≈ **$0.01**.
With no keys at all: **$0.00**.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `upload blocked: No YouTube credentials` | follow “Enable real uploads” above |
| uploads land as *private* | unverified API project — pass the audit, or approve manually in Studio |
| `quotaExceeded` | 1600 units/upload; wait for 00:00 PT reset or buy quota |
| edge-tts rate-limited | it's an unofficial endpoint; set `voice.provider: openai` |
| want different look | edit `config.yaml` colors/fonts, or swap `visuals.provider` |
| re-render after editing captions.ass | `python run.py run --run-id <id> --force` |

## Notes & ethics

* Shorts ≤60 s get the Shorts shelf; the 3-min Shorts window also works (`video.max_duration`).
* The uploader enforces a daily cap and keeps every video on disk — automation should
  stay reviewable. YouTube's spam policies punish mass-produced repetitive uploads;
  keep the niche tight and the quality bar high.
* edge-tts is an unofficial Microsoft endpoint: fine for personal automation,
  check terms before commercial scale. Music is synthesized in-process → zero copyright risk.
