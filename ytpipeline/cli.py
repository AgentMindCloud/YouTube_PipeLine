"""Command-line interface."""
import argparse
import sys
import time

from . import __version__
from .config import Config
from .state import Run


def _logo():
    print("┌─────────────────────────────────────────────┐")
    print("│  yt-pipeline · idea → video → YouTube       │")
    print("└─────────────────────────────────────────────┘")


def cmd_idea(cfg, args):
    from . import idea as idea_mod
    _logo()
    print(f"▶ Generating {args.count} ideas for niche: {cfg('channel.niche')}\n")
    ideas = idea_mod.generate_ideas(cfg, count=args.count)
    for i, it in enumerate(ideas, 1):
        print(f"  {i}. {it.get('title') or it.get('topic')}")
        print(f"     topic : {it.get('topic', '')}")
        print(f"     hook  : {it.get('hook', '')}")
        if it.get("why_it_works"):
            print(f"     why   : {it['why_it_works']}")
        print()
    if args.save:
        out = cfg.root / "output" / f"ideas-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(__import__("json").dumps(ideas, indent=2, ensure_ascii=False))
        print(f"  saved → {out.relative_to(cfg.root)}")
    print("  make one:  python run.py run --idea \"<topic>\"   (or --pick N from this list)")
    return 0


def cmd_run(cfg, args):
    from . import pipeline
    _logo()
    t0 = time.time()
    run = pipeline.execute(
        cfg,
        idea_text=args.idea,
        count=args.pick or 1,
        auto=args.auto,
        no_upload=args.no_upload,
        force=args.force,
        privacy=args.privacy,
        run_id=args.run_id,
    )
    print(f"\n⏱  finished in {time.time() - t0:.0f}s · run id: {run.id}")
    return 0


def cmd_approve(cfg, args):
    from . import pipeline
    _logo()
    pipeline.approve(cfg, args.run_id, privacy=args.privacy)
    return 0


def cmd_upload(cfg, args):
    from . import pipeline
    _logo()
    pipeline.upload_file(cfg, args.file, args.title, args.description or "",
                         tags=args.tags.split(",") if args.tags else None,
                         privacy=args.privacy)
    return 0


def cmd_auth(cfg, args):
    from . import youtube as yt
    if args.action == "login":
        yt.get_service(cfg)  # triggers OAuth flow / validates env creds
        name = yt.channel_name(cfg)
        print(f"  ✔ authenticated as channel: {name}")
        print("    (headless mode: copy client id/secret/refresh token from")
        print(f"     {cfg('upload.token_file')} into your CI secrets)")
    else:
        name = yt.channel_name(cfg)
        print(f"  auth status: {name}")
    return 0


def cmd_list(cfg, args):
    runs = Run.all_runs()
    if not runs:
        print("  no runs yet — create one: python run.py run")
        return 0
    print(f"  {'RUN ID':<48} {'STATE':<20} {'DUR':>5}  TITLE")
    for r in runs[:30]:
        dur = f"{r.get('duration', 0):.0f}s" if r.get("duration") else "-"
        print(f"  {r['run_id']:<48} {r.get('state', '?'):<20} {dur:>5}  {(r.get('title') or '')[:40]}")
    return 0


def cmd_status(cfg, args):
    import json
    run = Run.open(args.run_id)
    data = run.read()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    final = run.p("final.mp4")
    if final.exists():
        print(f"\n  video : {final}")
    up = run.load_json("upload_result.json")
    if up:
        print(f"  online: {up['url']}")
    elif data.get("state") == "awaiting_approval":
        print(f"\n  → publish with: python run.py approve {run.id}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="yt-pipeline",
        description="Automatic YouTube Shorts pipeline: idea → script → voice → visuals → render → upload.")
    ap.add_argument("--version", action="version", version=f"yt-pipeline {__version__}")
    ap.add_argument("--config", help="path to config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("idea", help="generate video ideas")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--save", action="store_true", help="save ideas to output/*.json")
    p.set_defaults(fn=cmd_idea)

    p = sub.add_parser("run", help="full pipeline: idea → rendered video (→ upload)")
    p.add_argument("--idea", help="custom topic/hook text")
    p.add_argument("--pick", type=int, help="generate N ideas, use the first")
    p.add_argument("--auto", action="store_true",
                   help="upload immediately after render (unattended/cron mode)")
    p.add_argument("--no-upload", action="store_true", help="stop after render")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"])
    p.add_argument("--force", action="store_true", help="regenerate cached stage artifacts")
    p.add_argument("--run-id", help="resume/retry an existing run")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("approve", help="upload a rendered run (human-in-the-loop gate)")
    p.add_argument("run_id")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"])
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("upload", help="upload any existing video file")
    p.add_argument("file")
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--tags", help="comma,separated,tags")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.set_defaults(fn=cmd_upload)

    p = sub.add_parser("auth", help="YouTube OAuth")
    p.add_argument("action", choices=["login", "status"])
    p.set_defaults(fn=cmd_auth)

    p = sub.add_parser("list", help="list all runs")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("status", help="show one run's status")
    p.add_argument("run_id")
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    cfg = Config(args.config)
    try:
        return args.fn(cfg, args) or 0
    except KeyboardInterrupt:
        print("\n  interrupted.")
        return 130
    except SystemExit as e:
        print(f"  ! {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
