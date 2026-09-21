"""Stage 3 — VOICE.  Per-beat TTS (OpenAI or free edge-tts), concatenated to one track.

Per-beat synthesis gives exact beat durations, which everything downstream
(captions, visuals, video cuts) is timed against.
"""
import asyncio
import re

import requests

from .media import probe_duration, run_ffmpeg, write_concat_list


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
    return r.content


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


def synthesize(cfg, beats, run, log=print, force=False):
    """Returns (voice_wav, beat_durations, word_timings|None, tempo_applied)."""
    voice = run.p("voice.wav")
    cached = run.load_json("durations.json") if not force else None
    if (not force and voice.exists() and voice.stat().st_size > 4000
            and cached and cached.get("durations")
            and len(cached["durations"]) == len(beats)):
        log("  reusing voice.wav + durations.json")
        words = run.load_json("words.json")
        return voice, cached["durations"], words, cached.get("tempo", 1.0)

    provider = cfg.resolve("voice")
    beat_dir = run.p("beats_audio")
    beat_dir.mkdir(exist_ok=True)

    wavs, all_words = [], []
    for i, beat in enumerate(beats):
        mp3 = beat_dir / f"b{i:02d}.mp3"
        wav = beat_dir / f"b{i:02d}.wav"
        words = None
        if force or not mp3.exists() or mp3.stat().st_size < 2000:
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
        if force or not wav.exists() or wav.stat().st_size < 2000:
            run_ffmpeg(["-i", str(mp3), "-ar", "44100", "-ac", "1", str(wav)], log)
        wavs.append(wav)
        if words:
            offset = sum(probe_duration(w) for w in wavs[:-1])
            all_words += [dict(w, s=w["s"] + offset, e=w["e"] + offset, beat=i) for w in words]
        if i == 0:
            if provider == "openai":
                log(f"  voice: OpenAI {cfg('voice.openai_voice')}")
            else:
                log(f"  voice: edge-tts {cfg('voice.edge_voice')} (free)")

    lst = write_concat_list(wavs, beat_dir / "concat.txt")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst),
                "-ar", "44100", "-ac", "1", str(voice)], log)

    durations = [probe_duration(w) for w in wavs]
    total = sum(durations)

    tempo, max_dur = 1.0, cfg("video.max_duration", 58)
    if total > max_dur:
        tempo = min(round(total / (max_dur - 0.5), 4), 1.35)
        fast = run.p("voice_fast.wav")
        run_ffmpeg(["-i", str(voice), "-filter:a", f"atempo={tempo}",
                    "-ar", "44100", "-ac", "1", str(fast)], log)
        voice = fast
        durations = [d / tempo for d in durations]
        all_words = [dict(w, s=w["s"] / tempo, e=w["e"] / tempo) for w in all_words]
        log(f"  ! narration was {total:.1f}s > {max_dur}s — sped up {tempo}x")

    return voice, durations, (all_words or None), tempo


def word_timings(beats, durations, edge_words=None, pad=0.03):
    """Word-level [{w,s,e,beat}] — exact edge-tts boundaries, else char-proportional estimate."""
    if edge_words and all(isinstance(w, dict) and "s" in w and "w" in w for w in edge_words):
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
        t = sum(durations[: i + 1])
    return words
