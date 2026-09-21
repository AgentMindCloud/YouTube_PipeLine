"""Stage 6 — MUSIC.  Procedurally synthesized royalty-free background track.

lofi   : mellow pad chords (Am-F-C-G) + soft kick + swung hats + vinyl hiss
ambient: pure evolving pad + hiss
No samples, no licensing, deterministic per duration.
"""
import wave

import numpy as np

SR = 44100

CHORDS = {  # Hz: A2 C3 E3 A3 etc.
    "Am": [110.00, 130.81, 164.81, 220.00, 261.63],
    "F":  [87.31, 110.00, 130.81, 174.61, 220.00],
    "C":  [130.81, 164.81, 196.00, 261.63, 329.63],
    "G":  [98.00, 123.47, 146.83, 196.00, 246.94],
}
PROG = ["Am", "F", "C", "G"]


def _lowpass(x, fc):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1.0 / (1.0 + (f / fc) ** 4)
    return np.fft.irfft(X, len(x))


def _saw_pad(freqs, n, rng, detune=0.004):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for mult, amp in ((1, 1.0), (2, 0.42), (3, 0.18)):
            d = 1 + rng.uniform(-detune, detune)
            out += amp / mult * np.sin(2 * np.pi * f * mult * d * t)
    return out / max(1, len(freqs))


def make_bgm(cfg, duration, path, log=print):
    style = (cfg("music.style") or "lofi").lower()
    if style == "none" or not cfg("music.enabled", True):
        return None
    duration += 2.0  # cover tail padding
    n = int(duration * SR)
    rng = np.random.default_rng(42)
    t = np.arange(n) / SR
    mix = np.zeros(n)
    bpm = float(cfg("music.bpm", 88))
    beat = 60.0 / bpm
    bar = beat * 4

    # pads: one chord per bar, slow attack/release
    for i, start in enumerate(np.arange(0, duration, bar)):
        s = int(start * SR)
        e = min(int((start + bar + 0.7) * SR), n)
        seg_n = e - s
        if seg_n <= 0:
            continue
        chord = PROG[i % len(PROG)]
        pad = _saw_pad(CHORDS[chord], seg_n, np.random.default_rng(i))
        env_t = np.arange(seg_n) / SR
        env = np.minimum(env_t / 0.5, 1.0) * np.minimum((seg_n / SR - env_t) / 0.8, 1.0)
        env = np.clip(env, 0, 1)
        mix[s:e] += _lowpass(pad * env, 950) * 0.30

    if style == "lofi":
        # soft kick on beats
        for k, bt in enumerate(np.arange(0, duration, beat)):
            s = int(bt * SR)
            ln = int(0.14 * SR)
            if s + ln > n:
                break
            tt = np.arange(ln) / SR
            f = 110 * np.exp(-tt * 22) + 44
            phase = 2 * np.pi * np.cumsum(f) / SR
            kick = np.sin(phase) * np.exp(-tt * 26)
            mix[s:s + ln] += kick * (0.5 if k % 4 == 0 else 0.36)
        # swung hats on 8ths
        for k, ht in enumerate(np.arange(0, duration, beat / 2)):
            s = int((ht + (0.03 if k % 2 else 0)) * SR)
            ln = int(0.035 * SR)
            if s + ln > n:
                break
            tt = np.arange(ln) / SR
            hat = _lowpass(rng.standard_normal(ln), 9000) * np.exp(-tt * 90)
            mix[s:s + ln] += hat * (0.10 if k % 2 == 0 else 0.055)

    # vinyl hiss
    mix += _lowpass(rng.standard_normal(n), 6500) * 0.010

    # stereo: haas-widen the pad via 11ms offset copy
    dly = int(0.011 * SR)
    left = np.concatenate([mix[:n - dly], np.zeros(dly)])
    right = mix
    stereo = np.stack([left, right], axis=1)

    # master: soft clip, fades
    stereo = np.tanh(stereo * 1.4) * 0.5
    fade_in = np.linspace(0, 1, int(1.2 * SR))[: n and int(1.2 * SR)]
    stereo[: len(fade_in)] *= fade_in[:, None]
    fo = min(int(2.0 * SR), n)
    stereo[-fo:] *= np.linspace(1, 0, fo)[:, None]

    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    log(f"  ✦ music: {style} @ {bpm:.0f} bpm, {duration:.0f}s (synthesized, royalty-free)")
    return path
