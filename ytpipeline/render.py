"""Stage 7 — RENDER.  ffmpeg assembly: Ken Burns segments → concat → captions,
music ducking, progress bar, fades → final 1080×1920 mp4."""
import json
import subprocess
from pathlib import Path

W, H = 1080, 1920


def _ff(args, log=None):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                       capture_output=True, text=True)
    if p.returncode != 0:
        if log:
            log(f"  ! ffmpeg error: {p.stderr.strip()[:600]}")
        raise RuntimeError("ffmpeg failed: " + " ".join(str(a) for a in args[:6]))
    return p


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])


def build_segments(cfg, run, beat_images, durations, log=print):
    """One zoompan mp4 per beat (exact frame counts)."""
    fps = int(cfg("video.fps", 30))
    zoom = float(cfg("video.ken_burns_zoom", 0.10))
    seg_dir = run.p("segments")
    seg_dir.mkdir(exist_ok=True)
    segs = []
    for i, (img, dur) in enumerate(zip(beat_images, durations)):
        frames = max(8, round(dur * fps))
        out = seg_dir / f"seg_{i:02d}.mp4"
        zmax = 1.0 + zoom
        if i % 2 == 0:  # zoom in
            z = f"min(1.0+{zoom}*on/{frames},{zmax:.4f})"
        else:           # zoom out
            z = f"max({zmax:.4f}-{zoom}*on/{frames},1.0)"
        vf = (f"scale=2160:3840:flags=lanczos,"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':"
              f"d={frames}:s={W}x{H}:fps={fps},format=yuv420p")
        _ff(["-i", str(img), "-vf", vf, "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
             "-r", str(fps), str(out)], log)
        segs.append(out)
    return segs


def concat_segments(run, segs):
    lst = run.p("segments") / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    out = run.p("video_only.mp4")
    _ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
    return out


def final_mix(cfg, run, video_only, voice, music_path, ass_path, total, log=print):
    """Captions + progress bar + fades + ducked music → final.mp4."""
    fps = int(cfg("video.fps", 30))
    tail = float(cfg("video.tail_padding", 0.8))
    vtotal = total + tail

    vchain = (
        f"[0:v]tpad=stop_mode=clone:stop_duration={tail:.2f},"
        f"ass={ass_path}:fontsdir={cfg.root / 'assets' / 'fonts'},"
        f"fade=t=in:st=0:d=0.25,fade=t=out:st={vtotal - 0.4:.3f}:d=0.4,"
        f"format=yuv420p[v]"
    )
    if music_path and Path(music_path).exists():
        vol = float(cfg("music.volume", 0.3))
        achain = (
            f"[1:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100,asplit=2[a1][sc];"
            f"[2:a]apad,volume={vol * 2.2:.3f},aresample=44100[bg];"
            f"[bg][sc]sidechaincompress=threshold=0.035:ratio=9:attack=12:release=350[bgd];"
            f"[a1][bgd]amix=inputs=2:duration=first:normalize=0,"
            f"afade=t=out:st={vtotal - 0.6:.3f}:d=0.55,atrim=0:{vtotal:.3f},"
            f"aresample=44100[aout]"
        )
        inputs = ["-i", str(video_only), "-i", str(voice), "-i", str(music_path)]
    else:
        achain = (
            f"[1:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100,apad,"
            f"afade=t=out:st={vtotal - 0.6:.3f}:d=0.55,atrim=0:{vtotal:.3f},"
            f"aresample=44100[aout]"
        )
        inputs = ["-i", str(video_only), "-i", str(voice)]

    final = run.p("final.mp4")
    _ff(inputs + [
        "-filter_complex", vchain + ";" + achain,
        "-map", "[v]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-r", str(fps), "-t", f"{vtotal:.3f}",
        "-movflags", "+faststart", str(final),
    ], log)
    return final


def render(cfg, run, script, beat_images, durations, voice, words, music_path, force=False, log=print):
    """Full assembly. Returns (final_path, video_duration)."""
    ass = run.p("captions.ass")
    final = run.p("final.mp4")
    total = sum(durations)
    if final.exists() and ass.exists() and not force:
        log("  ✓ final.mp4 already rendered (use --force to re-render)")
        return final, probe_duration(final)

    from .captions import build_ass
    build_ass(cfg, words, total, ass)

    log(f"  · rendering {len(beat_images)} Ken Burns segments…")
    segs = build_segments(cfg, run, beat_images, durations, log)
    video_only = concat_segments(run, segs)
    log("  · mixing voice, music, captions…")
    final = final_mix(cfg, run, video_only, voice, music_path, ass, total, log)
    dur = probe_duration(final)
    size_mb = final.stat().st_size / 1e6
    log(f"  ✦ rendered final.mp4  ({dur:.1f}s, {size_mb:.1f} MB)")
    return final, dur
