"""Stage 5 — CAPTIONS.  Word-by-word highlighted ASS subtitles (Shorts style)."""
import re


def _ass_color(hexcolor):
    c = hexcolor.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def _ts(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _clean(tok):
    return re.sub(r"[^\w']", "", tok).strip("'").upper()


def group_lines(words, max_words, max_chars):
    """Group words into short caption lines (never across beats)."""
    lines, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words
                    or sum(len(_clean(x["w"])) + 1 for x in cur + [w]) > max_chars
                    or w["beat"] != cur[-1]["beat"]):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def build_ass(cfg, words, total_duration, path):
    font = cfg("video.caption.font", "Archivo Black")
    size = int(cfg("video.caption.size", 88))
    hl = _ass_color(cfg("video.caption.highlight", "#FFD400"))
    wh = "&H00FFFFFF&"
    y = int(cfg("video.caption.y", 1300))
    max_words = int(cfg("video.caption.max_words_per_line", 3))
    max_chars = int(cfg("video.caption.max_chars_per_line", 24))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{wh},{wh},&H00000000,&HA0000000,-1,0,0,0,100,100,0.5,0,1,5,2.2,5,60,60,0,1
Style: Bar,{font},10,{wh},{wh},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # bottom progress bar as ASS vector drawings (portable across ffmpeg builds)
    bar_events = []
    step = 0.25
    nt = max(1, int(total_duration / step))
    for k in range(nt + 1):
        s = min(k * step, total_duration)
        e = min(s + step + 0.01, total_duration + 5)
        wpx = int(1080 * min((s + step / 2) / max(total_duration, 0.01), 1.0))
        bar_events.append(
            f"Dialogue: 2,{_ts(s)},{_ts(e)},Bar,,0,0,0,,"
            f"{{\\an7\\pos(0,1910)\\alpha&H26&\\p1}}m 0 0 l {wpx} 0 {wpx} 10 0 10{{\\p0}}")

    lines = group_lines(words, max_words, max_chars)
    events = []
    for li, line in enumerate(lines):
        line_s = line[0]["s"]
        line_e = line[-1]["e"]
        # tiny breathing room at line end, without overlapping next line
        next_s = lines[li + 1][0]["s"] if li + 1 < len(lines) else total_duration
        line_e = min(line_e + 0.14, next_s - 0.02, total_duration)
        tokens = [_clean(w["w"]) for w in line]
        for j, w in enumerate(line):
            s = max(w["s"], line_s - 0.05)
            e = min(w["e"] + 0.02, line_e)
            if j == len(line) - 1:
                e = line_e
            if e <= s:
                e = s + 0.06
            parts = []
            for k, tok in enumerate(tokens):
                color = hl if k == j else wh
                parts.append(f"{{\\c{color}}}{tok}")
            text = f"{{\\an5\\pos(540,{y})}}" + " ".join(parts)
            events.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{text}")

    path.write_text(header + "\n".join(bar_events + events) + "\n", encoding="utf-8")
    return path
