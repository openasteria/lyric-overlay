"""Точка входа: lyric-overlay / python -m lyric_overlay.main

Цикл:
  tick (update_interval_ms):
    1. TrackDetector.poll()          — что играет (MPRIS / заголовки окон Sway)
    2. GeniusClient.request(np)      — подтянуть текст (кэш/сеть, фоновый поток)
    3. LineSelector / Scroller       — активная строка или прокрутка
    4. OverlayWindow.update_text     — «Title, active line …next»
    5. WaybarState.write             — «♪ title» для waybar-модуля

Управление видимостью извне (клик по модулю Waybar / хоткей Sway):
  * SIGUSR1 — toggle;
  * файл-флаг ~/.local/state/lyric-overlay/toggle (touch = переключить).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

from .config import load_config
from .detection import TrackDetector
from .lyrics import GeniusClient, SongLyrics
from .sync import LineSelector, Scroller
from .track import NowPlaying
from .waybar import WaybarState

log = logging.getLogger("lyric-overlay")

TOGGLE_FLAG = Path(os.path.expanduser(
    "~/.local/state/lyric-overlay/toggle"))


class App:
    def __init__(self, cfg: dict, headless: bool = False):
        self.cfg = cfg
        self.headless = headless
        self.detector = TrackDetector(cfg)
        self.genius = GeniusClient(cfg)
        self.waybar = WaybarState(cfg)

        self.current: NowPlaying | None = None
        self.lyrics: SongLyrics | None = None
        self.selector: LineSelector | None = None
        self.scroller = Scroller(
            step_chars=float(cfg["lyrics"].get("scroll_step_chars_per_tick", 2)),
            pause_ticks=max(int(cfg["lyrics"].get("fetch_timeout_s", 8)) * 2, 6),
        )
        self._last_np_key = ""
        self._tick_count = 0
        self._preview_text = ""
        self.visible = True
        self.window = None

        if not headless:
            from .widget import OverlayWindow
            self.window = OverlayWindow(cfg, on_toggle_visibility=self.toggle)

        # Toggle через сигнал и файл-флаг (для хоткеев sway / waybar click)
        signal.signal(signal.SIGUSR1, lambda *_: self.toggle())
        TOGGLE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        self._toggle_mtime = self._flag_mtime()

    # ------------------------------------------------------------------
    def _flag_mtime(self) -> float:
        try:
            return TOGGLE_FLAG.stat().st_mtime
        except OSError:
            return 0.0

    def toggle(self) -> None:
        self.visible = not self.visible
        if self.window:
            self.window.set_visible(self.visible)
        log.info("Overlay %s", "shown" if self.visible else "hidden")

    # ------------------------------------------------------------------
    def on_lyrics_ready(self, np: NowPlaying, lyrics: SongLyrics | None) -> None:
        """Вызывается из фонового потока — только сохраняем результат."""
        if np.key() == (self.current.key() if self.current else ""):
            self.lyrics = lyrics
            if lyrics is not None:
                self.selector = LineSelector(self.current or np, lyrics)
                full = lyrics.plain().replace("\n", "   •   ")
                self.scroller.reset(len(full))
                log.info("Lyrics loaded for %r: %d lines (synced=%s)",
                         np.title, len(lyrics.lines), lyrics.synced)
            else:
                log.info("No lyrics found for %r (%s)", np.title, np.artist or "—")

    # ------------------------------------------------------------------
    def tick(self) -> bool:
        np = self.detector.poll()
        self.current = np

        # Смена трека → сброс текста и новый запрос
        key = np.key() if np else ""
        if key != self._last_np_key:
            self._last_np_key = key
            self.lyrics = None
            self.selector = None
            if np and np.title:
                self.genius.request(np, self.on_lyrics_ready)

        text = self.compose(np)
        self._preview_text = text

        if self.window and self.visible:
            self._render(np, text)
        self.waybar.write(np, self.visible, text)
        return True

    # ------------------------------------------------------------------
    def compose(self, np: NowPlaying | None) -> str:
        """Формирует строку вида «Title, active line … next part»."""
        if np is None or not np.title:
            return ""
        if self.lyrics is None:
            return "…loading lyrics…" if np.playing else ""
        if not self.lyrics.lines:
            return "(no lyrics found)"

        sel = self.selector
        assert sel is not None
        synced_mode = sel.can_sync(np) and self.lyrics.lines

        if synced_mode:
            idx = sel.active_index(np.position_s)
            active = self.lyrics.lines[idx].text
            nxt = (" " + self.lyrics.lines[idx + 1].text) if idx + 1 < len(self.lyrics.lines) else ""
            return f"{active}{(' …' + nxt.strip()) if nxt else ''}"
        # Прокрутка всего текста, если синхронизация невозможна
        full = "   •   ".join(l.text for l in self.lyrics.lines)
        approx_chars = int(self.cfg["widget"]["text_max_width"] / 7.2)
        frag, _ = self.scroller.window(full, approx_chars)
        self.scroller.tick()
        return frag

    def _render(self, np: NowPlaying | None, preview: str) -> None:
        assert self.window is not None
        title = np.title if np else ""
        if np is None:
            self.window.update_text("", "Nothing playing", "")
            self.window.set_status_dim(True)
            self.window.set_artwork("")
            return
        parts = preview.split(" …", 1)
        active_line = parts[0]
        next_part = ("… " + parts[1]) if len(parts) > 1 else ""
        if self.lyrics is None and np.playing:
            active_line = "loading lyrics…"
        self.window.update_text(title, active_line, next_part)
        self.window.set_status_dim(not np.playing)
        self.window.set_artwork(np.artwork_url)

    # ------------------------------------------------------------------
    def run_gtk(self) -> int:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk, GLib

        # NON_UNIQUE: несколько инстансов допустимы, но обычно он один
        try:
            flags = Gtk.ApplicationFlags.NON_UNIQUE
        except AttributeError:
            flags = 0
        app = Gtk.Application(application_id="io.github.lyric.overlay", flags=flags)
        win_holder = {}

        def activate(gapp):
            from .widget import OverlayWindow
            w = OverlayWindow(self.cfg, on_toggle_visibility=self.toggle)
            w.realize()
            win_holder["w"] = w
            self.window = w

        def on_tick():
            # файловый флаг toggle (touch ~/.local/state/lyric-overlay/toggle)
            m = self._flag_mtime()
            if m != self._toggle_mtime:
                self._toggle_mtime = m
                self.toggle()
            self.tick()
            return True

        app.connect("activate", activate)
        interval = int(self.cfg["lyrics"].get("update_interval_ms", 500))
        GLib.timeout_add(interval, on_tick)
        return app.run(None)

    def run_headless(self, duration: float | None = None) -> int:
        t0 = time.monotonic()
        interval = int(self.cfg["lyrics"].get("update_interval_ms", 500)) / 1000.0
        while True:
            self.tick()
            if duration is not None and time.monotonic() - t0 > duration:
                break
            time.sleep(interval)
        return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="lyric-overlay",
                                description="Lyrics overlay widget for Wayland/SwayWM")
    p.add_argument("-c", "--config", default=None, help="путь к config.yaml/json")
    p.add_argument("--headless", action="store_true",
                   help="без GUI: только детект+тексты+waybar state (отладка)")
    p.add_argument("--once", action="store_true", help="один тик и выход")
    p.add_argument("--duration", type=float, default=None,
                   help="запускать N секунд (вместе с --headless)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)
    log.info("Config: %s", cfg["_config_path"])
    app = App(cfg, headless=args.headless or args.once)
    if args.once:
        app.tick()
        print(app._preview_text or "(nothing playing)")
        return 0
    if args.headless:
        return app.run_headless(args.duration)
    try:
        return app.run_gtk()
    except RuntimeError as exc:
        log.error("GUI недоступен: %s", exc)
        log.error("Запустите в режиме отладки: lyric-overlay --headless")
        return 1


if __name__ == "__main__":
    sys.exit(main())
