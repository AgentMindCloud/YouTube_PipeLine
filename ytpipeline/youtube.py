"""Stage 8 — UPLOAD.  YouTube Data API v3, resumable, OAuth (file or env creds).

Two auth paths:
  A) interactive: client_secrets.json in project root → `python run.py auth login`
  B) headless/CI: YT_CLIENT_ID + YT_CLIENT_SECRET + YT_REFRESH_TOKEN env vars
"""
import json
import socket
import time
from pathlib import Path

from .state import upload_counter

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class UploadError(RuntimeError):
    pass


# ── credentials ──────────────────────────────────────────────────────────────
def _creds_from_env():
    import os
    cid, sec, tok = os.getenv("YT_CLIENT_ID"), os.getenv("YT_CLIENT_SECRET"), os.getenv("YT_REFRESH_TOKEN")
    if not (cid and sec and tok):
        return None
    from google.oauth2.credentials import Credentials
    creds = Credentials(token=None, refresh_token=tok, token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=sec, scopes=SCOPES)
    return creds


def _creds_from_file(cfg):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets = cfg.path(cfg("upload.client_secrets", "client_secrets.json"))
    token_file = cfg.path(cfg("upload.token_file", "output/token.json"))
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
    if creds and creds.valid:
        return creds
    if not secrets.exists():
        raise UploadError(
            f"No YouTube credentials found.\n"
            f"  Option A: put OAuth client JSON at {secrets} then run: python run.py auth login\n"
            f"  Option B: set YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN in .env\n"
            f"  (Google Cloud Console → enable 'YouTube Data API v3' → OAuth client ID 'Desktop app')")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    return creds


def get_service(cfg):
    from googleapiclient.discovery import build
    creds = _creds_from_env() or _creds_from_file(cfg)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_name(cfg):
    try:
        svc = get_service(cfg)
        r = svc.channels().list(part="snippet", mine=True).execute()
        items = r.get("items", [])
        return items[0]["snippet"]["title"] if items else None
    except Exception as e:
        return f"(auth check failed: {str(e)[:120]})"


# ── upload ───────────────────────────────────────────────────────────────────
def upload_video(cfg, video_path, metadata, privacy=None, thumb=None, log=print):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    today_count, bump = upload_counter()
    limit = int(cfg("upload.daily_upload_limit", 3))
    if today_count() >= limit:
        raise UploadError(f"daily upload limit reached ({limit}/day) — edit upload.daily_upload_limit in config.yaml")

    svc = get_service(cfg)
    title = metadata["title"][:100]
    desc_parts = [metadata.get("description", "")]
    tags_line = " ".join(h for h in cfg("upload.hashtags", ["#Shorts"]))
    if tags_line not in desc_parts[0]:
        desc_parts.append(tags_line)
    desc_parts.append(f"\n— {cfg('channel.name', '')} {cfg('channel.handle', '')} —")
    body = {
        "snippet": {
            "title": title,
            "description": "\n\n".join(p for p in desc_parts if p).strip()[:4900],
            "tags": metadata.get("tags", [])[:20],
            "categoryId": str(metadata.get("categoryId", cfg("upload.category_id", 22))),
        },
        "status": {
            "privacyStatus": privacy or metadata.get("privacyStatus") or cfg("upload.privacy_auto", "unlisted"),
            "madeForKids": bool(cfg("upload.made_for_kids", False)),
            "selfDeclaredMadeForKids": bool(cfg("upload.made_for_kids", False)),
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = svc.videos().insert(part="snippet,status", body=body, media_body=media)

    response, attempt = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                log(f"  · uploading… {int(status.progress() * 100)}%")
        except HttpError as e:
            code = getattr(e.resp, "status", 500)
            if code < 500 and code != 429:
                msg = str(e)
                hint = ""
                if "quotaExceeded" in msg:
                    hint = " (daily API quota exhausted — uploads cost 1600 units; quota resets 00:00 PT)"
                if "insufficientPermissions" in msg or "unverified" in msg.lower():
                    hint = " (unverified API project: uploads are locked to private until you pass the YouTube API audit — see README)"
                raise UploadError(f"YouTube API error {code}: {msg[:400]}{hint}")
            attempt += 1
            if attempt > 5:
                raise UploadError("upload failed after 5 retries")
            time.sleep(2 ** attempt)
        except (socket.timeout, ConnectionError, OSError) as e:
            attempt += 1
            if attempt > 5:
                raise UploadError(f"network failure: {e}")
            time.sleep(2 ** attempt)

    vid = response["id"]
    bump()
    url = f"https://youtube.com/shorts/{vid}"

    playlist = cfg("upload.playlist_id")
    if playlist:
        try:
            svc.playlistItems().insert(part="snippet", body={
                "snippet": {"playlistId": playlist,
                            "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            log(f"  ✓ added to playlist {playlist}")
        except Exception as e:
            log(f"  ! playlist insert failed: {str(e)[:150]}")

    if thumb and cfg("upload.thumbnail", True) and Path(thumb).exists():
        try:
            svc.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
            log("  ✓ custom thumbnail set")
        except Exception as e:
            log(f"  ! thumbnail set failed (needs verified API project): {str(e)[:120]}")

    return {"videoId": vid, "url": url}


def save_result(cfg, run, result):
    f = run.p("upload_result.json")
    f.write_text(json.dumps(result, indent=2))
    return f
