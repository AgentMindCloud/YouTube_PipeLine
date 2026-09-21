"""ffmpeg/ffprobe discovery and Windows-safe path helpers."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_FFMPEG = None
_FFPROBE = None


class MediaError(RuntimeError):
    pass


def _win_candidates(exe: str):
    home = Path.home()
    roots = [
        Path(os.environ.get("FFMPEG_PATH", "")),
        Path(r"C:\ffmpeg\bin"),
        Path(r"C:\Program Files\ffmpeg\bin"),
        Path(r"C:\Program Files (x86)\ffmpeg\bin"),
        home / "scoop" / "apps" / "ffmpeg" / "current" / "bin",
        home / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links",
        home / "AppData" / "Local" / "Programs" / "ffmpeg" / "bin",
    ]
    names = [f"{exe}.exe", exe]
    out = []
    for root in roots:
        if not root:
            continue
        for name in names:
            if root.is_dir():
                p = root / name
            else:
                p = root
            out.append(p)
    return out


def _resolve(exe: str) -> str:
    found = shutil.which(exe)
    if found:
        return found
    if os.name == "nt":
        found = shutil.which(f"{exe}.exe")
        if found:
            return found
        for cand in _win_candidates(exe):
            if cand.is_file():
                return str(cand)
    raise MediaError(
        f"{exe} not found on PATH. Windows: winget install Gyan.FFmpeg "
        f"then open a new terminal. Linux/macOS: sudo apt install ffmpeg / brew install ffmpeg."
    )


def ffmpeg_bin() -> str:
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = _resolve("ffmpeg")
    return _FFMPEG


def ffprobe_bin() -> str:
    global _FFPROBE
    if _FFPROBE is None:
        _FFPROBE = _resolve("ffprobe")
    return _FFPROBE


def run_ffmpeg(args, log=None):
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        err = (p.stderr or "").strip()[:600]
        if log:
            log(f"  ! ffmpeg error: {err}")
        raise RuntimeError(f"ffmpeg failed: {' '.join(str(a) for a in args[:6])}")
    return p


def probe_duration(path) -> float:
    import json
    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"ffprobe failed on {path}: {(out.stderr or '')[:300]}")
    return float(json.loads(out.stdout)["format"]["duration"])


def posix_path(path) -> str:
    """Forward-slash absolute path. ffmpeg on Windows accepts this."""
    return Path(path).resolve().as_posix()


def concat_file_line(path) -> str:
    """One concat-demuxer line. Single quotes escaped."""
    s = posix_path(path).replace("'", r"'\''")
    return f"file '{s}'"


def write_concat_list(paths, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(concat_file_line(p) + "\n" for p in paths), encoding="utf-8")
    return dest


def filter_path(path) -> str:
    """Escape a filesystem path for an ffmpeg filter argument (ass=, fontsdir=)."""
    s = posix_path(path)
    return s.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
