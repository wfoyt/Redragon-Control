"""First-run state, kept outside portable lighting and binding profiles."""

import json
from pathlib import Path

from .config import atomic_write


def keyboard_candidates(devices):
    """Known K686 connections; discovery also includes mice and other HID devices."""
    return [device for device in devices
            if device['id'].split('@')[0].lower() in ('258a:010c', '3554:fa09')]


class SetupStore:
    def __init__(self, config_path):
        path = Path(config_path)
        self.path = path.with_name(path.stem + ".setup.json")

    def completed(self):
        try:
            return json.loads(self.path.read_text()) == {"version": 1, "completed": True}
        except (OSError, ValueError):
            return False

    def finish(self):
        atomic_write(self.path, {"version": 1, "completed": True})
