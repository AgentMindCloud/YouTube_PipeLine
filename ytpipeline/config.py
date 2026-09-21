"""Configuration loading: config.yaml + .env environment."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


class Config:
    def __init__(self, path=None):
        load_dotenv(ROOT / ".env")
        cfg_path = Path(path) if path else ROOT / "config.yaml"
        if cfg_path.exists():
            self.data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        else:
            self.data = {}
        self.root = ROOT

    # dotted access: cfg("video.fps")
    def __call__(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, rel):
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    # -- environment helpers -------------------------------------------------
    @property
    def openai_key(self):
        return os.getenv("OPENAI_API_KEY", "").strip()

    @property
    def pexels_key(self):
        return os.getenv("PEXELS_API_KEY", "").strip()

    # -- provider resolution -------------------------------------------------
    def resolve(self, section):
        """'auto' -> best available provider for a section."""
        choice = (self(f"{section}.provider") or "auto").lower()
        if choice != "auto":
            return choice
        if section in ("script", "visuals"):
            return "openai" if self.openai_key else ("pexels" if section == "visuals" and self.pexels_key else "fallback" if section == "script" else "local")
        if section == "voice":
            return "openai" if self.openai_key else "edge"
        return choice
