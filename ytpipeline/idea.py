"""Stage 1 — IDEATION.  OpenAI-generated ideas, or the offline seed bank."""
import json
import time

import requests

from .config import ROOT

SEEDS = json.loads((ROOT / "ytpipeline" / "fallback" / "seeds.json").read_text())
USED_FILE = ROOT / "output" / "used_seeds.json"


def _used_seeds():
    if USED_FILE.exists():
        return json.loads(USED_FILE.read_text())
    return []


def _mark_used(seed_id):
    used = _used_seeds()
    if seed_id not in used:
        used.append(seed_id)
    USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    USED_FILE.write_text(json.dumps(used))


def openai_ideas(cfg, count=5, avoid=None):
    """Generate fresh ideas with GPT. Returns list of idea dicts."""
    prompt = (
        f"You are a viral YouTube Shorts strategist.\n"
        f"Channel niche: {cfg('channel.niche')}\n"
        f"Audience: {cfg('channel.audience')}\n"
        f"Tone: {cfg('channel.tone')}\n\n"
        f"Propose {count} video ideas that could realistically blow up as Shorts.\n"
        + (f"Avoid topics similar to these already-used ideas: {avoid}\n" if avoid else "")
        + "\nReply with ONLY a JSON object: {\"ideas\": [{\"topic\": str, \"title\": str, "
          "\"hook\": str (first spoken line, <=20 words), \"angle\": str, \"why_it_works\": str}]}"
    )
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg.openai_key}"},
        json={
            "model": cfg("script.model", "gpt-4o-mini"),
            "temperature": 1.0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    r.raise_for_status()
    data = json.loads(r.json()["choices"][0]["message"]["content"])
    return data.get("ideas", [])


def seed_ideas(count=5):
    """Next unused seeds from the offline bank (wraps around when exhausted)."""
    used = _used_seeds()
    fresh = [s for s in SEEDS if s["id"] not in used]
    if len(fresh) < count:
        used.clear()
        USED_FILE.write_text("[]")
        fresh = list(SEEDS)
    out = []
    for s in fresh[:count]:
        out.append({
            "topic": s["topic"], "title": s["title"], "hook": s["hook"],
            "angle": s.get("angle", ""), "why_it_works": "seed bank idea",
            "seed_id": s["id"],
        })
    return out


def generate_ideas(cfg, count=5, log=print):
    """auto: OpenAI when a key exists, otherwise the seed bank."""
    if cfg.resolve("script") == "openai":
        try:
            avoid = [s["topic"] for s in SEEDS if s["id"] in _used_seeds()]
            ideas = openai_ideas(cfg, count=count, avoid=avoid or None)
            if ideas:
                log(f"  ✦ {len(ideas)} fresh ideas from {cfg('script.model')}")
                return ideas
        except Exception as e:
            log(f"  ! OpenAI ideation failed ({e}) — using seed bank")
    return seed_ideas(count)


def next_seed_for(topic=None):
    """Pick the seed matching an idea (used by the fallback script writer)."""
    if topic:
        for s in SEEDS:
            if s["id"] == topic or s["topic"].lower() == topic.lower():
                return s
    for s in SEEDS:
        if s["id"] not in _used_seeds():
            return s
    return SEEDS[int(time.time()) % len(SEEDS)]


def mark_seed_used(idea):
    if idea.get("seed_id"):
        _mark_used(idea["seed_id"])
