"""Stage 2 — SCRIPT.  Beats of narration + on-screen text + visual prompts."""
import json
import re

import requests

from . import idea as idea_mod

BEAT_FIELDS = ("text", "on_screen", "visual_prompt", "broll_query")
_BAD_TAGS = {
    "shorts", "short", "youtube", "yt", "video", "videos", "youre", "you're",
    "your", "you", "the", "and", "for",
}


def clean_tags(tags, topic="", extra=None):
    out = []
    for t in list(tags or []) + list(extra or []):
        t = re.sub(r"[#]", "", str(t)).strip().lower()
        t = re.sub(r"\s+", " ", t)
        if len(t) < 3 or t in _BAD_TAGS:
            continue
        if t not in out:
            out.append(t[:30])
    for w in idea_mod._tok(topic):
        if w not in _BAD_TAGS and len(w) > 3 and w not in out:
            out.append(w)
    return out[:8] or ["psychology", "brain hacks", "facts"]


def openai_script(cfg, idea_dict):
    lo, hi = cfg("script.beats", [5, 7])
    wlo, whi = cfg("script.words", [95, 125])
    system = (
        "You write YouTube Shorts scripts that hook instantly and hold retention to the last second. "
        "Rules: first beat = cold-open hook (<=18 words, no intro, no 'hey guys'). "
        "One idea per beat. Plain spoken language, short sentences. "
        "Last beat = punchy takeaway + call to action, and must include \"type\": \"cta\". "
        "on_screen = 2-4 UPPERCASE words shown on screen for that beat. "
        "visual_prompt = one vivid, specific description for an AI image generator "
        "(dark cinematic style, never any text/letters inside the image). "
        "broll_query = 2-3 words to search stock photos."
    )
    user = (
        f"Channel niche: {cfg('channel.niche')}\nTone: {cfg('channel.tone')}\n"
        f"Audience: {cfg('channel.audience')}\n\n"
        f"Video idea: {idea_dict.get('topic')}\n"
        f"Suggested title: {idea_dict.get('title')}\n"
        f"Suggested hook (improve it if you can): {idea_dict.get('hook')}\n"
        f"Angle: {idea_dict.get('angle')}\n\n"
        f"Write the full script: {lo}-{hi} beats, {wlo}-{whi} total spoken words "
        f"(hard cap: it must be readable in {cfg('video.max_duration', 58)} seconds).\n"
        'Reply with ONLY JSON: {"title": str (<=70 chars, may contain 1 emoji), '
        '"description": str (1-2 sentences + 3-4 relevant hashtags, no #Shorts), '
        '"tags": [5-8 search tags], '
        '"beats": [{"text": str, "on_screen": str, "visual_prompt": str, "broll_query": str, "type": "cta" only on last}]}'
    )
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg.openai_key}"},
        json={
            "model": cfg("script.model", "gpt-4o-mini"),
            "temperature": cfg("script.temperature", 0.9),
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        },
        timeout=180,
    )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def fallback_script(cfg, idea_dict):
    """Offline: use a full seed script, or template-compose around a custom idea."""
    blob = " ".join(str(idea_dict.get(k) or "") for k in ("seed_id", "topic", "title", "hook"))
    seed = idea_mod.match_seed(blob) or idea_mod.next_seed_for(
        idea_dict.get("seed_id") or idea_dict.get("topic"))
    use_seed = bool(seed) and (
        idea_dict.get("seed_id") == seed["id"]
        or idea_mod.match_seed(blob) is not None and idea_mod.match_seed(blob)["id"] == seed["id"]
        or not idea_dict.get("custom")
    )
    if use_seed and seed:
        tags = clean_tags(seed.get("tags"), seed["topic"])
        hashes = " ".join(f"#{t.replace(' ', '')}" for t in tags[:4])
        script = {
            "title": seed["title"],
            "description": f"{seed['hook']}\n\n{hashes}",
            "tags": tags,
            "beats": [dict(b) for b in seed["beats"]],
            "source_seed": seed["id"],
        }
        idea_dict.setdefault("seed_id", seed["id"])
        return script

    hook = idea_dict.get("hook") or idea_dict.get("topic")
    topic = idea_dict.get("topic") or hook
    tags = clean_tags([], topic=topic, extra=["psychology", "brain hacks", "mindset"])
    hashes = " ".join(f"#{t.replace(' ', '')}" for t in tags[:4])
    cta = cfg("channel.cta_line", "Follow for more.")
    script = {
        "title": (idea_dict.get("title") or topic)[:70],
        "description": f"{hook}\n\n{hashes}",
        "tags": tags,
        "beats": [
            {"text": hook.rstrip(".") + ".",
             "on_screen": "WAIT FOR THIS",
             "visual_prompt": f"cinematic dark illustration about: {topic}, dramatic lighting, no text",
             "broll_query": topic[:30]},
            {"text": "Most people treat this like a personality trait. It isn't. It's a fear loop.",
             "on_screen": "IT'S A FEAR LOOP",
             "visual_prompt": "a crowd of grey silhouettes with one glowing figure seeing hidden connections, dark cinematic, no text",
             "broll_query": "fear loop brain"},
            {"text": "Name the real job in one sentence. Shrink it until it takes two minutes. Start there.",
             "on_screen": "SHRINK THE TASK",
             "visual_prompt": "a giant glowing task list being sliced down to one tiny card, dark background, cyan accent light, no text",
             "broll_query": "tiny checklist"},
            {"text": f"Do the two-minute version now. {cta}",
             "on_screen": "DO IT NOW", "type": "cta",
             "visual_prompt": "a glowing countdown timer hitting zero with golden light, dark background, no text",
             "broll_query": "timer countdown"},
        ],
        "source_seed": None,
    }
    return script


def normalize(cfg, script):
    beats = []
    for b in script.get("beats", []):
        if isinstance(b, str):
            b = {"text": b}
        beat = {
            "text": re.sub(r"\s+", " ", str(b.get("text", ""))).strip(),
            "on_screen": re.sub(r"\s+", " ", str(b.get("on_screen", ""))).strip().upper()[:34],
            "visual_prompt": re.sub(r"\s+", " ", str(b.get("visual_prompt", "abstract dark cinematic texture, glowing shapes"))).strip(),
            "broll_query": re.sub(r"\s+", " ", str(b.get("broll_query", "abstract background"))).strip()[:60],
            "type": "cta" if str(b.get("type", "")).lower() == "cta" else "",
        }
        if beat["text"]:
            beats.append(beat)
    if not beats:
        raise ValueError("script has no narration beats")
    if not any(b["type"] == "cta" for b in beats):
        beats[-1]["type"] = "cta"
    title = re.sub(r"\s+", " ", str(script.get("title", "Untitled Short"))).strip()[:95]
    tags = clean_tags(script.get("tags"), title)
    desc = str(script.get("description", "") or title).strip()
    return {"title": title, "description": desc, "tags": tags, "beats": beats,
            "source_seed": script.get("source_seed")}


def write_script(cfg, idea_dict, log=print):
    provider = cfg.resolve("script")
    if provider == "openai":
        try:
            raw = openai_script(cfg, idea_dict)
            log(f"  script by {cfg('script.model')}")
            return normalize(cfg, raw)
        except Exception as e:
            log(f"  ! OpenAI script failed ({e}) — falling back to seed bank")
    raw = fallback_script(cfg, idea_dict)
    log(f"  script from offline seed bank ({raw.get('source_seed') or 'template'})")
    return normalize(cfg, raw)
