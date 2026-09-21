# yt-pipeline

YouTube Shorts factory: idea → script → voice → visuals → karaoke captions
(with a bottom progress bar in `captions.ass`) → music → 1080×1920 render →
human approve → YouTube.

Zero API keys still works (seed bank + edge-tts + local art + synthesized lofi).
Windows is first-class. See **SETUP.windows.md**.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
python run.py doctor
python run.py run --no-upload
python run.py list
```

Install ffmpeg first:

- Windows: `winget install Gyan.FFmpeg` then open a new terminal
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

Then `python run.py approve <run-id>` after you watch `output/<run-id>/final.mp4`.

Do **not** commit `output/` or `final.mp4`. Copy `.env.example` → `.env` locally.

## Commands

| Command | What it does |
|---|---|
| `python run.py doctor` | ffmpeg, fonts, keys, OAuth |
| `python run.py idea [--count N]` | writes `output/last_ideas.json` |
| `python run.py run --pick N` | render idea N from that list |
| `python run.py run --idea "topic"` | custom topic |
| `python run.py run --no-upload` | render only |
| `python run.py run --run-id ID` | resume; skips finished voice/visuals |
| `python run.py run --force` | regenerate artifacts |
| `python run.py approve <id>` | upload after you watched it |
| `python run.py auth login` | YouTube OAuth (re-run after v1.1 for new scopes) |

Progress bar is drawn in `captions.ass` (not a separate ffmpeg overlay).

## YouTube

Enable YouTube Data API v3, Desktop OAuth client → `client_secrets.json` → `auth login`.
Unverified projects lock uploads to private. Daily cap in `config.yaml` defaults to 3.

## v1.1

Windows path-safe ffmpeg concat + ASS fontsdir, `doctor`, real `--pick`, voice resume,
broader YouTube scopes, `.gitignore` / `.env.example` on GitHub.
