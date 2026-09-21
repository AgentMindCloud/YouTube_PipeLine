"""Orchestrator: idea → script → voice → visuals → captions → music → render → upload."""
import json
import time
from pathlib import Path

from . import idea as idea_mod
from . import music as music_mod
from . import render as render_mod
from . import script as script_mod
from . import tts as tts_mod
from . import visuals as vis_mod
from . import youtube as yt_mod
from .state import Run


def _pack_metadata(cfg, run, script, idea_dict, duration, providers):
    meta = {
        "title": script["title"],
        "description": script["description"],
        "tags": script["tags"],
        "categoryId": str(cfg("upload.category_id", 22)),
        "privacyStatus": cfg("upload.privacy_auto", "unlisted"),
        "madeForKids": bool(cfg("upload.made_for_kids", False)),
        "video": "final.mp4",
        "thumbnail": "thumb.png",
        "duration": round(duration, 2),
        "run_id": run.id,
        "idea": idea_dict,
        "providers": providers,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    run.save_json("metadata.json", meta)
    return meta


def _load_picked_idea(cfg, pick):
    path = cfg.root / "output" / "last_ideas.json"
    if not path.exists():
        raise SystemExit("No output/last_ideas.json — run `python run.py idea` first, then `--pick N`.")
    ideas = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(ideas, list) or not ideas:
        raise SystemExit("last_ideas.json is empty — run `python run.py idea` again.")
    if pick < 1 or pick > len(ideas):
        raise SystemExit(f"--pick {pick} out of range (1–{len(ideas)}).")
    return ideas[pick - 1]


def execute(cfg, idea_text=None, pick=None, auto=False, no_upload=False, force=False,
            privacy=None, run_id=None, log=print):
    """Run the whole pipeline. Returns the Run."""
    if run_id:
        run = Run.open(run_id)
        idea_dict = run.load_json("idea.json") or {"topic": run.read().get("title", "video"), "custom": True}
        log(f"Resuming run {run.id}")
    else:
        if idea_text:
            idea_dict = {"topic": idea_text, "title": idea_text[:70], "hook": idea_text,
                         "angle": "", "custom": True}
            log(f"Idea (from --idea): {idea_text[:80]}")
        elif pick:
            idea_dict = _load_picked_idea(cfg, pick)
            log(f"Idea (pick #{pick}): {idea_dict.get('topic', idea_dict.get('title', ''))[:80]}")
        else:
            log("Stage 1/8  IDEATE")
            ideas = idea_mod.generate_ideas(cfg, count=3, log=log)
            idea_dict = ideas[0]
            for alt in ideas[1:]:
                log(f"    spare idea: {alt.get('topic', alt.get('title', ''))[:70]}")
            log(f"  chosen: {idea_dict.get('topic', idea_dict.get('title'))[:80]}")
        run = Run.create(idea_dict.get("title") or idea_dict["topic"])
        log(f"  run dir: output/{run.id}")
    run.save_json("idea.json", idea_dict)

    log("Stage 2/8  SCRIPT")
    script = run.load_json("script.json") if not force else None
    if not script:
        script = script_mod.write_script(cfg, idea_dict, log=log)
        run.save_json("script.json", script)
        idea_mod.mark_seed_used(idea_dict)
    else:
        log("  reusing script.json")
    words_total = sum(len(b["text"].split()) for b in script["beats"])
    log(f"  {len(script['beats'])} beats, {words_total} words — {script['title']}")

    log("Stage 3/8  VOICE")
    voice, durations, edge_words, tempo = tts_mod.synthesize(
        cfg, script["beats"], run, log=log, force=force)
    run.save_json("durations.json", {"durations": durations, "tempo": tempo})
    if (not force and edge_words and run.p("words.json").exists()
            and isinstance(edge_words, list) and edge_words and "s" in edge_words[0]):
        words = edge_words
    else:
        words = tts_mod.word_timings(script["beats"], durations, edge_words)
        run.save_json("words.json", words)
    log(f"  narration {sum(durations):.1f}s, {len(words)} timed words")

    log("Stage 4/8  VISUALS")
    beat_images = vis_mod.render_beats(cfg, script, run, force=force, log=log)

    log("Stage 5/8  MUSIC")
    music_path = run.p("music.wav")
    if not music_path.exists() or force:
        music_path = music_mod.make_bgm(cfg, sum(durations), music_path, log=log)
    else:
        log("  reusing music.wav")

    log("Stage 6/8  RENDER")
    final, duration = render_mod.render(cfg, run, script, beat_images, durations,
                                        voice, words, music_path, force=force, log=log)

    log("Stage 7/8  PACKAGE")
    thumb = vis_mod.make_thumbnail(cfg, script, beat_images, run)
    providers = {"script": cfg.resolve("script"), "voice": cfg.resolve("voice"),
                 "visuals": cfg.resolve("visuals")}
    meta = _pack_metadata(cfg, run, script, idea_dict, duration, providers)
    run.update(stage="rendered", state="awaiting_approval", title=script["title"],
               duration=round(duration, 1))
    log(f"  metadata.json + {thumb.name}")

    log("Stage 8/8  UPLOAD")
    if no_upload:
        log("  --no-upload: stopping after render.")
        _print_ready(run, meta)
    elif auto:
        _do_upload(cfg, run, meta, privacy, log)
    else:
        _print_ready(run, meta)
    return run


def _print_ready(run, meta):
    print()
    print(f"  VIDEO READY   output/{run.id}/final.mp4   ({meta['duration']}s)")
    print(f"    Title : {meta['title']}")
    print(f"    Tags  : {', '.join(meta['tags'][:6])}")
    print("    Watch it, then publish with:")
    print(f"      python run.py approve {run.id}")
    print(f"      python run.py approve {run.id} --privacy public")


def _do_upload(cfg, run, meta, privacy, log):
    try:
        result = yt_mod.upload_video(cfg, run.p(meta["video"]), meta,
                                     privacy=privacy, thumb=run.p(meta["thumbnail"]), log=log)
        yt_mod.save_result(cfg, run, result)
        run.update(stage="uploaded", state="uploaded", video_id=result["videoId"],
                   url=result["url"], privacy=privacy or meta["privacyStatus"])
        log(f"  UPLOADED ({privacy or meta['privacyStatus']}): {result['url']}")
        return result
    except yt_mod.UploadError as e:
        run.update(stage="render", state="awaiting_approval", upload_error=str(e)[:500])
        log(f"  ! upload blocked: {e}")
        log(f"    video is safe on disk — retry later with: python run.py approve {run.id}")
        return None


def approve(cfg, run_id, privacy=None, log=print):
    run = Run.open(run_id)
    meta = run.load_json("metadata.json")
    if not meta:
        raise SystemExit(f"{run_id} has no metadata.json — run: python run.py run --run-id {run_id}")
    if run.read().get("state") == "uploaded":
        print(f"Already uploaded: {run.read().get('url')}")
        return run
    log(f"Uploading {meta['title']} ({meta['duration']}s)")
    _do_upload(cfg, run, meta, privacy, log)
    return run


def upload_file(cfg, path, title, description="", tags=None, privacy="private", log=print):
    meta = {"title": title or Path(path).stem, "description": description,
            "tags": tags or ["shorts"], "categoryId": cfg("upload.category_id", 22),
            "privacyStatus": privacy}
    run = Run.create(f"manual-{meta['title']}")
    result = yt_mod.upload_video(cfg, Path(path), meta, privacy=privacy, log=log)
    yt_mod.save_result(cfg, run, result)
    run.update(stage="uploaded", state="uploaded", url=result["url"])
    log(f"  UPLOADED: {result['url']}")
    return result
