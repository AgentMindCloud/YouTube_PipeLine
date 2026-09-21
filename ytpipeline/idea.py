"""Stage 1 — IDEATION.  OpenAI-generated ideas, or the offline seed bank."""
import json
import re
import time

import requests

from .config import ROOT

SEEDS = json.loads((ROOT / "ytpipeline" / "fallback" / "seeds.json").read_text(encoding="utf-8"))
USED_FILE = ROOT / "output" / "used_seeds.json"

_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "is", "it", "in", "on", "for",
    "that", "this", "your", "you", "not", "with", "from",
}


def _norm(s):
    s = (s or "").lower().replace("—", "-").replace("–", "-").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tok(s):
    return {t for t in _norm(s).split() if t and t not in _STOP and len(t) > 1}


def match_seed(text, min_score=0.34):
    """Best seed whose title/topic/hook overlaps `text`. None if weak."""
    qn = _norm(text)
    q = _tok(text)
    if not qn:
        return None
    best, best_sc = None, 0.0
    for s in SEEDS:
        sc = 0.0
        if s.get("id") and _norm(s["id"].replace("-", " ")) == qn:
            sc = 1.0
        for f in (s.get("id", "").replace("-", " "), s.get("topic", ""),
                  s.get("title", ""), s.get("hook", "")):
            fn = _norm(f)
            if not fn:
                continue
            if qn == fn or qn in fn or fn in qn:
                sc = max(sc, 0.95)
            ft = _tok(f)
            if ft and q:
                sc = max(sc, len(q & ft) / len(q | ft))
        if sc > best_sc:
            best, best_sc = s, sc
    return best if best_sc >= min_score else None


def idea_from_seed(seed):
    return {
        "topic": seed["topic"],
        "title": seed["title"],
        "hook": seed["hook"],
        "angle": seed.get("angle", ""),
        "why_it_works": seed.get("angle", "seed bank idea"),
        "seed_id": seed["id"],
        "custom": False,
    }


def _used_seeds():
    if USED_FILE.exists():
        return json.loads(USED_FILE.read_text(encoding="utf-8"))
    return []


def _mark_used(seed_id):
    used = _used_seeds()
    if seed_id not in used:
        used.append(seed_id)
    USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    USED_FILE.write_text(json.dumps(used), encoding="utf-8")


def openai_ideas(cfg, count=5, avoid=None):
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
    used = _used_seeds()
    fresh = [s for s in SEEDS if s["id"] not in used]
    if len(fresh) < count:
        used.clear()
        USED_FILE.write_text("[]", encoding="utf-8")
        fresh = list(SEEDS)
    return [idea_from_seed(s) for s in fresh[:count]]


def generate_ideas(cfg, count=5, log=print):
    if cfg.resolve("script") == "openai":
        try:
            avoid = [s["topic"] for s in SEEDS if s["id"] in _used_seeds()]
            ideas = openai_ideas(cfg, count=count, avoid=avoid or None)
            if ideas:
                log(f"  {len(ideas)} fresh ideas from {cfg('script.model')}")
                return ideas
        except Exception as e:
            log(f"  ! OpenAI ideation failed ({e}) — using seed bank")
    return seed_ideas(count)


def next_seed_for(topic=None):
    if topic:
        hit = match_seed(topic)
        if hit:
            return hit
        for s in SEEDS:
            if s["id"] == topic or s["topic"].lower() == str(topic).lower():
                return s
    for s in SEEDS:
        if s["id"] not in _used_seeds():
            return s
    return SEEDS[int(time.time()) % len(SEEDS)]


def mark_seed_used(idea):
    if idea.get("seed_id"):
        _mark_used(idea["seed_id"])
