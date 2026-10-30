"""Загрузка конфигурации (YAML или JSON) со значениями по умолчанию."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "widget": {
        "anchor_corner": "top-left",
        "margin_x": 12,
        "margin_y": 12,
        "layer": "overlay",
        "exclusive_zone": 0,
        "keyboard_interactive": "none",
        "height": 36,
        "icon_size": 38,
        "text_min_width": 146,
        "text_max_width": 520,
        "corner_radius": 5,
        "icon_gap": 10,
        "colors": {
            "background": "#1e1e1e",
            "text_active": "#ffffff",
            "text_inactive": "#888888",
            "icon_fallback_bg": "#2a2a2a",
        },
        "font": {"family": "Figtree", "fallback_family": "Sans", "size_px": 14},
        "opacity": 1.0,
        "show_title_prefix": True,
        "title_separator": ", ",
    },
    "lyrics": {
        "genius_token_env": "GENIUS_TOKEN",
        "genius_token": "",
        "cache_dir": "~/.cache/lyric-overlay",
        "fetch_timeout_s": 8,
        "scroll_when_unsynced": True,
        "scroll_step_chars_per_tick": 2,
        "update_interval_ms": 500,
    },
    "detection": {
        "sources": ["mpris", "window_title"],
        "mpris": {"ignore_players": [], "prefer": []},
        "window_title": {
            "patterns": {
                "youtube": [r"^(?P<title>.+?)\s+[–—-]\s+YouTube\s+[–—-]\s+"],
                "soundcloud": [r"^(?P<title>.+?)\s+[–—-]\s+SoundCloud"],
                "mpv": [r"^\s*MPV\s*\(\s*(?P<file>[^)]+)\)\s*$"],
                "generic_browser": [
                    r"^(?P<title>.+?)\s+[–—-]\s+(Mozilla Firefox|Google Chrome|Chromium)\s*$"
                ],
            },
            "cleanup_regex": r"\s*[\[(](Official (Music )?Video|Audio|HD|Lyrics?|Visualizer)[\])].*$",
            "poll_interval_ms": 1000,
        },
    },
    "waybar": {
        "enabled": True,
        "state_file": "~/.local/state/lyric-overlay/waybar.json",
        "tooltip": "Click to toggle lyric overlay",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно сливает override в копию base (dict'ы сливаются, остальное заменяется)."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_raw(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # PyYAML
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Для YAML-конфига нужен PyYAML (pip install pyyaml) "
                "или используйте JSON-конфиг."
            ) from exc
        return yaml.safe_load(text) or {}
    return json.loads(text)


def default_config_path() -> Path:
    """Стандартные пути поиска конфига."""
    candidates = [
        Path(os.environ.get("LYRIC_OVERLAY_CONFIG", "")).expanduser()
        if os.environ.get("LYRIC_OVERLAY_CONFIG")
        else None,
        Path.cwd() / "config" / "config.yaml",
        Path.home() / ".config" / "lyric-overlay" / "config.yaml",
        Path.home() / ".config" / "lyric-overlay" / "config.json",
        Path("/etc/lyric-overlay/config.yaml"),
    ]
    for c in candidates:
        if c is not None and c.is_file():
            return c
    # Репозиторий: <root>/config/config.yaml рядом с пакетом
    repo_cfg = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
    return repo_cfg


def load_config(path: str | os.PathLike | None = None) -> dict:
    """Загружает конфиг и подмешивает значения по умолчанию."""
    cfg_path = Path(path).expanduser() if path else default_config_path()
    user_cfg: dict = {}
    if cfg_path.is_file():
        user_cfg = _load_raw(cfg_path)
    merged = _deep_merge(DEFAULT_CONFIG, user_cfg)
    merged["_config_path"] = str(cfg_path)
    return merged


def genius_token(cfg: dict) -> str:
    """Токен Genius: из config.lyrics.genius_token либо из переменной окружения."""
    lyr = cfg.get("lyrics", {})
    tok = (lyr.get("genius_token") or "").strip()
    if not tok:
        tok = os.environ.get(lyr.get("genius_token_env", "GENIUS_TOKEN"), "").strip()
    return tok
