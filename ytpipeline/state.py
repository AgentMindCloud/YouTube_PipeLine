"""Run bookkeeping: each video gets output/<run_id>/ with status.json + artifacts."""
import json
import re
import time
from pathlib import Path

from .config import ROOT

OUTPUT = ROOT / "output"


def _slugify(text, maxlen=40):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen] or "video"


class Run:
    def __init__(self, run_id):
        self.id = run_id
        self.dir = OUTPUT / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.dir / "status.json"

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def create(cls, title):
        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slugify(title)}"
        run = cls(run_id)
        run.update(stage="created", state="running", title=title)
        return run

    @classmethod
    def open(cls, run_id):
        run = cls(run_id)
        if not run.status_file.exists():
            raise SystemExit(f"Run not found: {run_id}  (try: python run.py list)")
        return run

    def update(self, **fields):
        data = self.read()
        data.update(fields)
        data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.status_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def read(self):
        if self.status_file.exists():
            return json.loads(self.status_file.read_text())
        return {"run_id": self.id}

    # -- artifacts -----------------------------------------------------------
    def p(self, *parts):
        return self.dir.joinpath(*parts)

    def save_json(self, name, obj):
        self.p(name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))

    def load_json(self, name, default=None):
        f = self.p(name)
        return json.loads(f.read_text()) if f.exists() else default

    @classmethod
    def all_runs(cls):
        if not OUTPUT.exists():
            return []
        runs = []
        for d in sorted(OUTPUT.iterdir(), reverse=True):
            sf = d / "status.json"
            if d.is_dir() and sf.exists():
                try:
                    runs.append(json.loads(sf.read_text()))
                except Exception:
                    pass
        return runs


def upload_counter():
    """Per-day upload counts for the daily_upload_limit safety valve."""
    f = OUTPUT / "uploads.json"
    data = json.loads(f.read_text()) if f.exists() else {}
    today = time.strftime("%Y-%m-%d")

    def today_count():
        return data.get(today, 0)

    def bump():
        data[time.strftime("%Y-%m-%d")] = today_count() + 1
        f.write_text(json.dumps(data, indent=2))

    return today_count, bump
