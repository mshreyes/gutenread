"""Tiny JSON persistence for settings, reading progress and cached books."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("GUTENREAD_HOME", Path.home() / ".gutenread"))
CACHE_DIR = DATA_DIR / "books"
STATE_FILE = DATA_DIR / "state.json"

DEFAULTS = {
    "settings": {"theme": "Midnight", "font": "", "size": 44, "wpm": 300,
                 "punct": True, "orp": True},
    "progress": {},   # book key -> {"title": str, "idx": int}
    "last": None,     # metadata needed to reopen the last book
}


def load() -> dict:
    data = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        data["settings"].update(saved.get("settings", {}))
        data["progress"] = saved.get("progress", {})
        data["last"] = saved.get("last")
    except (OSError, ValueError):
        pass
    return data


def save(data: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except OSError:
        pass
