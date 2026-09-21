"""Stage 4 — VISUALS.  One 1080×1920 image per beat.

Provider chain (config visuals.provider, default auto):
  openai  → gpt-image-1 / dall-e-3 generated art
  pexels  → free stock photos matched to broll_query
  local   → built-in Pillow renderer (gradients + bokeh + beat number), always works

Every provider's output gets the same branded overlay: channel handle,
big on-screen text, and a SUBSCRIBE button on the CTA beat.
"""
import base64
import random
import re

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ROOT

W, H = 1080, 1920
FONTS = ROOT / "assets" / "fonts"
ARCHIVO = FONTS / "ArchivoBlack-Regular.ttf"
POP_BOLD = FONTS / "Poppins-Bold.ttf"
POP_SEMI = FONTS / "Poppins-SemiBold.ttf"


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _font(path, size):
    return ImageFont.truetype(str(path), size)


def _fit(draw, text, font_path, max_size, max_width, max_lines=2):
    words = text.split()
    font, lines = _font(font_path, max_size), [text]
    for size in range(max_size, 28, -4):
        font = _font(font_path, size)
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= max_lines:
            return font, lines
    return font, lines


# ── local renderer (always available) ───────────────────────────────────────
def local_visual(cfg, beat, idx, n_beats):
    rng = random.Random(hash(beat["visual_prompt"]) & 0xFFFF)
    colors = [_hex(c) for c in cfg("video.brand_colors", ["#7C3AED", "#06B6D4", "#F59E0B"])]
    accent = colors[idx % len(colors)]
    black = (8, 8, 16)

    # vertical gradient: accent-tinted top → near-black bottom
    top, bot = _mix(accent, black, 0.70), _mix(accent, black, 0.90)
    t = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(top)[None, None, :] * (1 - t) + np.array(bot)[None, None, :] * t)
    arr = np.repeat(arr, W, axis=1)
    img = Image.fromarray(arr.astype(np.uint8), "RGB")

    # bokeh blobs
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(5):
        r = rng.randint(160, 420)
        x, y = rng.randint(-100, W + 100), rng.randint(100, H - 100)
        c = colors[rng.randrange(len(colors))]
        gd.ellipse([x - r, y - r, x + r, y + r], fill=c + (rng.randint(26, 64),))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img.convert("RGBA"), glow)

    # semi-transparent elements must be drawn on a separate layer, then composited
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    # giant beat number, low alpha, behind everything
    num = f"{idx + 1:02d}"
    fnum = _font(ARCHIVO, 560)
    bbox = ld.textbbox((0, 0), num, font=fnum)
    ld.text(((W - (bbox[2] - bbox[0])) // 2 - bbox[0], 690), num, font=fnum, fill=(255, 255, 255, 34))

    # thin accent rule above the on-screen text
    ld.rounded_rectangle([W // 2 - 90, 470, W // 2 + 90, 482], 6, fill=accent + (235,))
    img = Image.alpha_composite(img, layer)

    # film grain
    g = cfg("visuals.grain", 0.05)
    if g > 0:
        noise = np.random.default_rng(idx).normal(0, g * 255, (H, W, 1))
        arr2 = np.clip(np.asarray(img.convert("RGB")).astype(np.float32) + noise, 0, 255)
        img = Image.fromarray(arr2.astype(np.uint8), "RGB").convert("RGBA")

    # vignette
    yy, xx = np.mgrid[0:H, 0:W]
    dist = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 1.414
    vig = np.clip(1 - 0.5 * dist ** 2.4, 0, 1)[:, :, None]
    arr3 = np.asarray(img.convert("RGB")).astype(np.float32) * vig
    img = Image.fromarray(np.clip(arr3, 0, 255).astype(np.uint8), "RGB")
    return img


# ── AI / stock providers ─────────────────────────────────────────────────────
def openai_visual(cfg, beat, idx):
    model = cfg("visuals.openai_model", "gpt-image-1")
    prompt = f"{cfg('visuals.style_prefix', '')}. Scene: {beat['visual_prompt']}"
    body = {"model": model, "prompt": prompt, "n": 1}
    if model.startswith("gpt-image"):
        body["size"] = "1024x1536"
        body["quality"] = cfg("visuals.openai_quality", "medium")
    else:  # dall-e-3
        body["size"] = "1024x1792"
        body["response_format"] = "url"
    r = requests.post("https://api.openai.com/v1/images/generations",
                      headers={"Authorization": f"Bearer {cfg.openai_key}"},
                      json=body, timeout=300)
    r.raise_for_status()
    item = r.json()["data"][0]
    if "b64_json" in item:
        import io
        return Image.open(io.BytesIO(base64.b64decode(item["b64_json"]))).convert("RGB")
    resp = requests.get(item["url"], timeout=120)
    resp.raise_for_status()
    import io
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def pexels_visual(cfg, beat, idx):
    r = requests.get("https://api.pexels.com/v1/search",
                     headers={"Authorization": cfg.pexels_key},
                     params={"query": beat.get("broll_query") or beat["on_screen"],
                             "orientation": "portrait", "per_page": 4}, timeout=30)
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        raise RuntimeError("no pexels results")
    url = photos[idx % len(photos)]["src"].get("large2x") or photos[idx % len(photos)]["src"]["original"]
    img = requests.get(url, timeout=60)
    img.raise_for_status()
    import io
    return Image.open(io.BytesIO(img.content)).convert("RGB")


def _cover(img, w=W, h=H):
    """Crop-resize any image to exact w×h."""
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


# ── branded overlay (applied to every provider) ─────────────────────────────
def overlay_text(cfg, img, beat, idx):
    img = img.convert("RGBA")

    # everything drawn on a transparent layer, composited once (correct alpha blending)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # channel handle watermark
    handle = cfg("channel.handle", "")
    if handle:
        fh = _font(POP_SEMI, 42)
        d.text((W // 2, 130), handle, font=fh, fill=(255, 255, 255, 165),
               anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0, 140))

    # big on-screen text
    text = beat.get("on_screen") or ""
    if text:
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        f, lines = _fit(probe, text, ARCHIVO, 118, 920, max_lines=2)
        line_h = f.size * 1.12
        y0 = 640 - line_h * (len(lines) - 1) / 2
        for i, ln in enumerate(lines):
            d.text((W // 2, y0 + i * line_h), ln, font=f, fill=(255, 255, 255, 255),
                   anchor="mm", stroke_width=8, stroke_fill=(0, 0, 0, 255))

    # CTA beat → red subscribe button
    if beat.get("type") == "cta":
        bw, bh, by = 620, 150, 950
        d.rounded_rectangle([W // 2 - bw // 2, by - bh // 2, W // 2 + bw // 2, by + bh // 2],
                            30, fill=(255, 0, 0, 255), outline=(255, 255, 255, 255), width=4)
        fb = _font(ARCHIVO, 66)
        d.text((W // 2 + 30, by), "SUBSCRIBE", font=fb, fill=(255, 255, 255, 255), anchor="mm")
        cx = W // 2 - 230  # play triangle
        d.polygon([(cx - 22, by - 30), (cx - 22, by + 30), (cx + 30, by)], fill=(255, 255, 255, 255))

    img = Image.alpha_composite(img, layer)
    return img.convert("RGB")


def render_beats(cfg, script, run, force=False, log=print):
    """Returns list of beat image paths (1080×1920)."""
    provider = cfg.resolve("visuals")
    beat_dir = run.p("beats")
    beat_dir.mkdir(exist_ok=True)
    beats = script["beats"]
    paths = []
    for i, beat in enumerate(beats):
        out = beat_dir / f"beat_{i:02d}.png"
        if out.exists() and not force:
            paths.append(out)
            continue
        img = None
        if provider in ("openai", "auto"):
            try:
                img = openai_visual(cfg, beat, i)
                log(f"  ✦ beat {i + 1}/{len(beats)}: image by {cfg('visuals.openai_model')}")
            except Exception as e:
                log(f"  ! beat {i + 1} AI image failed ({str(e)[:100]}) — next provider")
        if img is None and provider in ("pexels", "auto") and cfg.pexels_key:
            try:
                img = pexels_visual(cfg, beat, i)
                log(f"  ✦ beat {i + 1}/{len(beats)}: photo via Pexels")
            except Exception as e:
                log(f"  ! beat {i + 1} pexels failed ({str(e)[:80]}) — local renderer")
        if img is None:
            img = local_visual(cfg, beat, i, len(beats))
            if i == 0:
                log(f"  ✦ visuals: built-in renderer (no API key needed)")
        img = overlay_text(cfg, _cover(img), beat, i)
        img.save(out, "PNG")
        paths.append(out)
    return paths


def make_thumbnail(cfg, script, beat_paths, run):
    """1280×720 custom thumbnail (Shorts mostly ignore it, long-form needs it)."""
    src = Image.open(beat_paths[min(1, len(beat_paths) - 1)]).convert("RGB")
    tw, th = 1280, 720
    scale = max(tw / src.width, th / src.height)
    src = src.resize((int(src.width * scale), int(src.height * scale)), Image.Resampling.LANCZOS)
    x, y = (src.width - tw) // 2, int((src.height - th) * 0.35)
    img = src.crop((x, y, x + tw, y + th)).convert("RGBA")

    shade = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for yy in range(th):  # bottom-up darkening
        a = int(190 * (yy / th) ** 1.4)
        sd.line([(0, yy), (tw, yy)], fill=(5, 5, 12, a))
    img = Image.alpha_composite(img, shade)

    d = ImageDraw.Draw(img)
    title = re.sub(r"[^\w\s!?.,—-]", "", script["title"]).strip() or script["title"]
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f, lines = _fit(probe, title, ARCHIVO, 92, tw - 120, max_lines=2)
    line_h = f.size * 1.1
    y0 = th - 60 - line_h * (len(lines) - 1)
    for i, ln in enumerate(lines):
        d.text((60, y0 + i * line_h), ln, font=f, fill=(255, 255, 255, 255),
               anchor="lm", stroke_width=6, stroke_fill=(0, 0, 0, 240))
    accent = _hex(cfg("video.brand_colors", ["#7C3AED"])[0])
    d.rounded_rectangle([60, 50, 340, 104], 12, fill=accent + (255,))
    fh = _font(POP_BOLD, 34)
    d.text((200, 77), "SHORTS", font=fh, fill=(255, 255, 255, 255), anchor="mm")
    out = run.p("thumb.png")
    img.convert("RGB").save(out)
    return out
