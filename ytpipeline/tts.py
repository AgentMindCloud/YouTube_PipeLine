"""Stage 3 — VOICE.  Per-beat TTS (OpenAI or free edge-tts), concatenated to one track.

Per-beat synthesis gives exact beat durations, which everything downstream
(captions, visuals, video cuts) is timed against.
"""
import asyncio
import json
import re
import subprocess

import requests


def _ff(args, log=None):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                       capture_output=True, text=True)
    if p.returncode != 0 and log:
        log(f"  ! ffmpeg: {p.stderr.strip()[:400]}")
    p.check_returncode()


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)], capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])


# ── providers ────────────────────────────────────────────────────────────────
def _openai_speech(cfg, text):
    r = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {cfg.openai_key}"},
        json={
            "model": cfg("voice.openai_model", "gpt-4o-mini-tts"),
            "voice": cfg("voice.openai_voice", "onyx"),
            "input": text,
            "speed": cfg("voice.openai_speed", 1.0),
            "response_format": "mp3",
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.content  # mp3 bytes, no word timings


def _edge_speech(cfg, text):
    """edge-tts: free Microsoft neural voices + exact word-boundary timestamps."""
    import edge_tts

    async def _collect():
        comm = edge_tts.Communicate(
            text, cfg("voice.edge_voice", "en-US-ChristopherNeural"),
            rate=cfg("voice.edge_rate", "+0%"), boundary="WordBoundary")
        audio, words = bytearray(), []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "w": chunk["text"],
                    "s": chunk["offset"] / 10_000_000,
                    "e": (chunk["offset"] + chunk["duration"]) / 10_000_000,
                })
        return bytes(audio), words

    return asyncio.run(_collect())


# ── main entry ───────────────────────────────────────────────────────────────
def synthesize(cfg, beats, run, log=print):
    """Returns (voice_wav, beat_durations, word_timings|None, tempo_applied)."""
    provider = cfg.resolve("voice")
    beat_dir = run.p("beats_audio")
    beat_dir.mkdir(exist_ok=True)

    wavs, all_words = [], []
    for i, beat in enumerate(beats):
        mp3 = beat_dir / f"b{i:02d}.mp3"
        wav = beat_dir / f"b{i:02d}.wav"
        if not mp3.exists() or mp3.stat().st_size < 2000:
            if provider == "openai":
                try:
                    mp3.write_bytes(_openai_speech(cfg, beat["text"]))
                    words = None
                except Exception as e:
                    log(f"  ! OpenAI TTS failed ({e}) — beat {i} via edge-tts")
                    audio, words = _edge_speech(cfg, beat["text"])
                    mp3.write_bytes(audio)
            else:
                audio, words = _edge_speech(cfg, beat["text"])
                mp3.write_bytes(audio)
        else:
            words = None
        _ff(["-i", str(mp3), "-ar", "44100", "-ac", "1", str(wav)])
        wavs.append(wav)
        if words:
            offset = sum(probe_duration(w) for w in wavs[:-1])
            all_words += [dict(w, s=w["s"] + offset, e=w["e"] + offset, beat=i) for w in words]
        if provider == "openai" and i == 0:
            log(f"  ✦ voice: OpenAI {cfg('voice.openai_voice')}")
        elif provider != "openai" and i == 0:
            log(f"  ✦ voice: edge-tts {cfg('voice.edge_voice')} (free)")

    voice = run.p("voice.wav")
    lst = beat_dir / "concat.txt"
    lst.write_text("".join(f"file '{w}'\n" for w in wavs))
    _ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-ar", "44100", "-ac", "1", str(voice)])

    durations = [probe_duration(w) for w in wavs]
    total = sum(durations)

    # Shorts guard: if narration exceeds the cap, gently speed it up.
    tempo, max_dur = 1.0, cfg("video.max_duration", 58)
    if total > max_dur:
        tempo = min(round(total / (max_dur - 0.5), 4), 1.35)
        _ff(["-i", str(voice), "-filter:a", f"atempo={tempo}", "-ar", "44100", "-ac", "1",
             run.p("voice_fast.wav")])
        voice = run.p("voice_fast.wav")
        durations = [d / tempo for d in durations]
        all_words = [dict(w, s=w["s"] / tempo, e=w["e"] / tempo) for w in all_words]
        log(f"  ! narration was {total:.1f}s > {max_dur}s → sped up {tempo}×")

    return voice, durations, (all_words or None), tempo


def word_timings(beats, durations, edge_words=None, pad=0.03):
    """Word-level [{w,s,e,beat}] — exact edge-tts boundaries, else char-proportional estimate."""
    if edge_words:
        # align boundary tokens to beats by cumulative time
        starts, out = [], 0.0
        for i, d in enumerate(durations):
            starts.append((out, i))
            out += d
        def beat_of(t):
            b = 0
            for s, i in starts:
                if t >= s - 0.05:
                    b = i
            return b
        return [dict(w, beat=beat_of(w["s"])) for w in edge_words
                if re.sub(r"[^\w']", "", w["w"])]

    words, t = [], 0.0
    for i, (beat, dur) in enumerate(zip(beats, durations)):
        toks = beat["text"].split()
        weights = [max(len(re.sub(r"[^\w']", "", x)) + 1, 2) for x in toks]
        total_w = sum(weights)
        for tok, wt in zip(toks, weights):
            d = dur * wt / total_w
            clean = re.sub(r"[^\w']", "", tok)
            if clean:
                words.append({"w": tok, "s": t + pad, "e": t + d, "beat": i})
            t += d
        t = sum(durations[: i + 1])  # snap to exact beat boundary
    return words
