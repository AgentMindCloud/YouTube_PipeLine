# Windows setup

This repo is meant to run on `C:\\Users\\<you>\\Desktop\\yt-pipeline` (or any local folder).

## 1. Tools

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

Close and reopen the terminal so PATH updates. Check:

```powershell
python --version
ffmpeg -version
ffprobe -version
```

If `ffmpeg` is still missing, install to `C:\\ffmpeg` and add `C:\\ffmpeg\\bin` to PATH, or set `FFMPEG_PATH` to that folder.

## 2. Project

```powershell
cd C:\\Users\\louis\\Desktop\\yt-pipeline
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python run.py doctor
```

`doctor` must show ffmpeg + fonts as ✔ before you render.

## 3. First Short (no upload)

```powershell
python run.py run --no-upload --idea "You're not lazy — your brain is scared"
```

Watch `output\\<run-id>\\final.mp4`. Resume without redoing TTS/images:

```powershell
python run.py run --run-id <run-id> --no-upload
```

Force a clean re-render:

```powershell
python run.py run --run-id <run-id> --no-upload --force
```

## 4. Pick an idea

```powershell
python run.py idea --count 5
python run.py run --pick 2 --no-upload
```

## 5. YouTube (optional)

1. Google Cloud → YouTube Data API v3 → OAuth Desktop client
2. Save JSON as `client_secrets.json` in the project root (gitignored)
3. `python run.py auth login`
4. `python run.py approve <run-id>`

Keep privacy `unlisted` or `private` until the API project is verified.

## Notes

- `output/` is local-only. `final.mp4` is too large for GitHub.
- Do not commit `.env`, `client_secrets.json`, or `output/token.json`.
- Pull v1.1+ before rendering on Windows (concat list + ASS font paths).
