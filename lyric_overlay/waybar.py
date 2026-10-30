"""Запись состояния для Waybar (модуль `custom/lyric`).

Waybar-модуль запускает команду, которая печатает JSON вида:
    {"text": "♪ Bohemian Rhapsody", "tooltip": "...", "class": "playing"}
Мы пишем этот JSON в файл состояния; скрипт scripts/waybar-module.sh просто
`cat`-ит его — мгновенно и без сетевых задержек.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from .track import NowPlaying

log = logging.getLogger("lyric-overlay.waybar")


class WaybarState:
    def __init__(self, cfg: dict):
        wb = cfg.get("waybar", {})
        self.enabled = bool(wb.get("enabled", True))
        self.state_file = Path(
            os.path.expanduser(wb.get("state_file",
                                      "~/.local/state/lyric-overlay/waybar.json"))
        )
        self.tooltip_tpl = wb.get("tooltip", "Lyric overlay")
        if self.enabled:
            try:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                log.warning("Не создать каталог waybar-состояния: %s", exc)
                self.enabled = False

    def write(self, np: Optional[NowPlaying], visible: bool,
              lyric_preview: str = "") -> None:
        if not self.enabled:
            return
        if np and np.playing and np.title:
            text = f"♪ {np.title}"
            cls = "playing"
            tip_lines = [f"<b>{np.title}</b>"]
            if np.artist:
                tip_lines.append(np.artist)
            if lyric_preview:
                tip_lines.append("")
                tip_lines.append(lyric_preview)
        elif np and np.title:
            text, cls = f"♪ {np.title}", "paused"
            tip_lines = [f"<b>{np.title}</b>", "Paused"]
        else:
            text, cls = "♪", "idle"
            tip_lines = ["Nothing playing"]
        payload = {
            "text": text,
            "alt": cls,
            "class": cls,
            "tooltip": "\n".join(tip_lines),
            "visible": visible,
        }
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.state_file)
        except OSError as exc:
            log.debug("waybar state write failed: %s", exc)
