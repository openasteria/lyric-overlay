"""Детекция текущего трека.

Источники (по порядку из config.detection.sources):
  1. MPRIS через D-Bus (dbus-fast / dbus_next / PyGIO) — Spotify, mpv, browsers
     с расширением MPRIS, локальные плееры.
  2. Заголовки окон SwayWM (`swaymsg -t get_tree`) + regex-паттерны из конфига —
     YouTube/SoundCloud во Firefox/Chromium, mpv и т.п.

PulseAudio/PipeWire используются опционально: через `pactl` мы можем понять,
у какого приложения идёт активный аудиопоток (для приоритета окна браузера).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from typing import Iterable, Optional

from .track import (
    NowPlaying,
    clean_title,
    filename_to_title,
    split_artist_title,
)

log = logging.getLogger("lyric-overlay.detect")

MPRIS_SERVICE_GLOB = "org.mpris.MediaPlayer2.*"
MPRIS_IFACE = "org.mpris.MediaPlayer2"
MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


# ---------------------------------------------------------------------------
# MPRIS (D-Bus)
# ---------------------------------------------------------------------------

class MprisDetector:
    """Опрос всех MPRIS-плееров в сессийном D-Bus. Работает поверх трёх бэкендов."""

    def __init__(self, cfg: dict):
        self.ignore = {s.lower() for s in cfg.get("mpris", {}).get("ignore_players", [])}
        self.prefer = [s.lower() for s in cfg.get("mpris", {}).get("prefer", [])]
        self._backend = self._pick_backend()

    # -- выбор бэкенда ------------------------------------------------------
    @staticmethod
    def _pick_backend():
        try:
            import dbus_fast  # noqa: F401
            return "dbus_fast"
        except ImportError:
            pass
        try:
            import dbus_next  # noqa: F401
            return "dbus_next"
        except ImportError:
            pass
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio  # noqa: F401
            return "gio"
        except (ImportError, ValueError):
            return None

    # -- публичный API ------------------------------------------------------
    def available(self) -> bool:
        if self._backend is None:
            log.warning("Нет D-Bus бэкенда (pip install dbus-fast или python3-gi) — MPRIS недоступен")
            return False
        return True

    def get_now_playing(self) -> Optional[NowPlaying]:
        if not self.available():
            return None
        try:
            if self._backend == "gio":
                return self._query_gio()
            return self._query_cli()
        except Exception as exc:  # pragma: no cover — сеть/DBus могут отказать
            log.debug("MPRIS query failed: %s", exc)
            return None

    # -- gio-бэкенд (синхронный, без event loop) ----------------------------
    def _query_gio(self) -> Optional[NowPlaying]:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def call(dest, path, iface, method, params=None):
            return bus.call_sync(
                dest, path, iface, method,
                GLib.Variant("(a{sv})", (params or {},)) if False else None,
                None, Gio.DBusCallFlags.NONE, 800, None,
            )

        # Список имён сервисов MPRIS
        reply = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "ListNames", None, None,
            Gio.DBusCallFlags.NONE, 800, None,
        )
        names = [n for (n,) in [(x,) for x in reply.unpack()[0]]
                 if n.startswith(MPRIS_SERVICE_GLOB[:-1])]
        names = [n for n in reply.unpack()[0] if str(n).startswith("org.mpris.MediaPlayer2.")]

        best: Optional[NowPlaying] = None
        for name in sorted(names):
            player_id = name.rsplit(".", 1)[-1].lower()
            if player_id in self.ignore:
                continue
            try:
                props_v = bus.call_sync(
                    name, "/org/mpris/MediaPlayer2",
                    "org.freedesktop.DBus.Properties", "GetAll",
                    GLib.Variant("(s)", (MPRIS_PLAYER_IFACE,)), None,
                    Gio.DBusCallFlags.NONE, 800, None,
                )
                props = props_v.unpack()[0]
                playstatus = str(props.get("PlaybackStatus", ("",))[1])
                metadata = props.get("Metadata", ({},))[1] if "Metadata" in props else props.get("Metadata", {})
                # GetAll возвращает a{sv}: значения уже варианны; unpack даёт кортежи-обёртки
                md = {}
                for k, v in metadata.items():
                    md[k] = v[1] if isinstance(v, tuple) and len(v) == 2 else v
                np = self._build(player_id, playstatus, md)
            except Exception as exc:
                log.debug("MPRIS %s: %s", name, exc)
                continue
            if np is None:
                continue
            if self._better(np, best):
                best = np
        return best

    # -- CLI-бэкенд (busctl / gdbus) -----------------------------------------
    def _query_cli(self) -> Optional[NowPlaying]:
        """Fallback без python-библиотек: gdbus introspection + Properties.GetAll."""
        tool = shutil.which("gdbus") or shutil.which("busctl")
        if not tool:
            return None
        try:
            if "gdbus" in tool:
                out = subprocess.run(
                    [tool, "--session", "list-names"],
                    capture_output=True, text=True, timeout=3,
                ).stdout
                names = [n.strip() for n in out.splitlines()
                         if n.strip().startswith("org.mpris.MediaPlayer2.")]
            else:
                out = subprocess.run(
                    [tool, "--user", "list", "org.mpris.MediaPlayer2"],
                    capture_output=True, text=True, timeout=3,
                ).stdout
                names = [ln.split()[-1] for ln in out.splitlines()
                         if "org.mpris.MediaPlayer2." in ln]
        except Exception:
            return None

        best = None
        for name in names:
            pid = name.rsplit(".", 1)[-1].lower()
            if pid in self.ignore:
                continue
            np = self._query_one_cli(tool, name, pid)
            if np and self._better(np, best):
                best = np
        return best

    def _query_one_cli(self, tool: str, service: str, player_id: str) -> Optional[NowPlaying]:
        try:
            if tool.endswith("gdbus"):
                txt = subprocess.run(
                    [tool, "--session", "call", "--timeout", "1",
                     service, "/org/mpris/MediaPlayer2",
                     "org.freedesktop.DBus.Properties", "GetAll",
                     "org.mpris.MediaPlayer2.Player"],
                    capture_output=True, text=True, timeout=3,
                ).stdout
                playstatus = _regex_group(txt, r"'PlaybackStatus'.*?'([a-z]+)'")
                title = _regex_group(txt, r"'xesam:title'.*?<string>(.*?)</string>") \
                    or _regex_group(txt, r"'xesam:title',\s*<string>(.*?)</string>") \
                    or _regex_group(txt, r"'xesam:title'\s+variant\s+'?([^']*)'?", "")
                artist_j = _regex_group(txt, r"'xesam:artist'.*?\[([^]]*)\]")
                art = _regex_group(txt, r"'mpris:artUrl'.*?<string>(.*?)</string>") \
                    or _regex_group(txt, r"'mpris:artUrl'\s+variant\s+'([^']*)'")
                pos_us = _regex_group(txt, r"'Position'.*?(\d+)")
            else:  # busctl
                txt = subprocess.run(
                    [tool, "--user", "get-property", service,
                     "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
                     "PlaybackStatus", "Metadata"],
                    capture_output=True, text=True, timeout=3,
                ).stdout
                playstatus = _regex_group(txt, r'"([A-Za-z]+)"')
                title = _regex_group(txt, r'"xesam:title"[^"]*"([^"]*)"')
                artist_j = _regex_group(txt, r'"xesam:artist"[^]]*\]', "")
                art = _regex_group(txt, r'"mpris:artUrl"[^"]*"([^"]*)"')
                pos_us = ""
            md = {"xesam:title": title or "", "xesam:artist": artist_j or "",
                  "mpris:artUrl": art or ""}
            np = self._build(player_id, playstatus or "", md)
            if np and pos_us:
                try:
                    np.position_s = int(pos_us) / 1_000_000.0
                except ValueError:
                    pass
            return np
        except Exception as exc:
            log.debug("MPRIS cli %s: %s", service, exc)
            return None

    # -- сборка NowPlaying из метаданных -------------------------------------
    def _build(self, player_id: str, status: str, md: dict) -> Optional[NowPlaying]:
        raw_title = str(md.get("xesam:title") or "").strip()
        url = str(md.get("xesam:url") or "")
        if not raw_title and url:
            raw_title = filename_to_title(url.rsplit("/", 1)[-1])
        if not raw_title:
            return None
        artist_val = md.get("xesam:artist") or ""
        if isinstance(artist_val, (list, tuple)):
            artist = ", ".join(str(a) for a in artist_val)
        else:
            artist = str(artist_val)
        title = clean_title(raw_title)
        if title == raw_title and not artist:
            a, t = split_artist_title(raw_title)
            artist, title = (a, t) if t else ("", title)
        playing = status.lower() == "playing"
        length = md.get("mpris:length")
        try:
            length_s = float(length) / 1_000_000.0 if length else 0.0
        except (TypeError, ValueError):
            length_s = 0.0
        return NowPlaying(
            title=title or raw_title,
            artist=artist,
            source=f"mpris:{player_id}",
            playing=playing,
            length_s=length_s,
            artwork_url=str(md.get("mpris:artUrl") or ""),
            raw={"player": player_id, "status": status},
        )

    def _better(self, cand: NowPlaying, cur: Optional[NowPlaying]) -> bool:
        """Приоритет: указанный в prefer > играет сейчас > есть ранее."""
        if cur is None:
            return True
        cid = cand.raw.get("player", "").lower()
        uid = cur.raw.get("player", "").lower()
        pi = {p: i for i, p in enumerate(self.prefer)}
        if cid in pi and uid in pi:
            return pi[cid] < pi[uid]
        if cid in pi:
            return True
        if uid in pi:
            return False
        return cand.playing and not cur.playing


def _regex_group(text: str, pattern: str, default: str = "") -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else default


# ---------------------------------------------------------------------------
# Заголовки окон SwayWM
# ---------------------------------------------------------------------------

class WindowTitleDetector:
    """Читает дерево Sway (`swaymsg -t get_tree`) и матчит заголовки окон с паттернами."""

    def __init__(self, cfg: dict):
        wt = cfg.get("window_title", {})
        self.patterns: dict[str, list[re.Pattern]] = {
            src: [re.compile(p) for p in plist]
            for src, plist in (wt.get("patterns") or {}).items()
        }
        cleanup = wt.get("cleanup_regex")
        self.cleanup = re.compile(cleanup) if cleanup else None
        self.swaymsg = shutil.which("swaymsg")

    def available(self) -> bool:
        return self.swaymsg is not None

    def _windows(self) -> Iterable[dict]:
        assert self.swaymsg
        try:
            out = subprocess.run(
                [self.swaymsg, "-t", "get_tree"],
                capture_output=True, text=True, timeout=3,
            ).stdout
            tree = json.loads(out)
        except Exception as exc:
            log.debug("swaymsg get_tree failed: %s", exc)
            return []
        stack = [tree]
        while stack:
            node = stack.pop()
            props = node.get("props") or {}
            if props.get("type") == "con" and node.get("window_name"):
                yield {"name": node["window_name"],
                       "app_id": (props.get("window_properties") or {}).get("class")
                                 or props.get("app_id") or "",
                       "focused": bool(node.get("focused"))}
            for child in (node.get("nodes", []) + node.get("floating_nodes", [])):
                stack.append(child)

    def _active_audio_clients(self) -> set[str]:
        """Приложения с активным аудиопотоком (PipeWire/WirePlumber через pw-cli,
        либо PulseAudio/pactl). Используется как подсказка приоритета окна."""
        clients: set[str] = set()
        try:
            if shutil.which("wpctl"):
                out = subprocess.run(["wpctl", "status"], capture_output=True,
                                     text=True, timeout=2).stdout
                for line in out.splitlines():
                    if "AUDIO_STREAM" in line and ("*" in line or "STREAMING" in line.upper()):
                        m = re.search(r"\]\s+#\d+\.\s+(.+)$", line)
                        if m:
                            clients.add(m.group(1).strip().lower())
            elif shutil.which("pactl"):
                out = subprocess.run(["pactl", "list", "sink-inputs"],
                                     capture_output=True, text=True, timeout=2).stdout
                for m in re.finditer(r"application\.name\s*=\s*\"([^\"]+)\"", out):
                    clients.add(m.group(1).lower())
        except Exception:
            pass
        return clients

    def get_now_playing(self) -> Optional[NowPlaying]:
        if not self.available():
            return None
        audio = self._active_audio_clients()
        candidates: list[tuple[int, NowPlaying]] = []
        for win in self._windows():
            name = win["name"]
            app = win["app_id"].lower()
            score = 1 if win["focused"] else 0
            if any(a and (a in app or app in a) for a in audio):
                score += 2
            for source, regs in self.patterns.items():
                for rx in regs:
                    m = rx.search(name)
                    if not m:
                        continue
                    gd = m.groupdict()
                    text = (gd.get("title") or name).strip()
                    if source == "mpv" or "file" in gd:
                        base = filename_to_title(gd.get("file", text))
                        artist, title = split_artist_title(base)
                        title = clean_title(title) or title
                    else:
                        artist, t2 = split_artist_title(text)
                        title = clean_title(t2 or text)
                        # если после очистки остался «Artist» — артист известен
                        if title != t2 and artist == t2:
                            artist = ""
                    if not title:
                        continue
                    if self.cleanup:
                        title = self.cleanup.sub("", title).strip()
                    src_label = {"youtube": "youtube", "soundcloud": "soundcloud",
                                 "mpv": "mpv"}.get(source, f"browser:{app or 'unknown'}")
                    np = NowPlaying(title=title, artist=artist, source=src_label,
                                    playing=True, raw={"window": name})
                    candidates.append((score, np))
                    break
                else:
                    continue
                break
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]


# ---------------------------------------------------------------------------
# Комбинированный детектор
# ---------------------------------------------------------------------------

class TrackDetector:
    """Опрашивает источники по очереди и отдаёт актуальный NowPlaying."""

    def __init__(self, cfg: dict):
        det = cfg.get("detection", {})
        sources = det.get("sources", ["mpris", "window_title"])
        self.mpris = MprisDetector(det) if "mpris" in sources else None
        self.window = WindowTitleDetector(det) if "window_title" in sources else None
        self.poll_ms = int(det.get("window_title", {}).get("poll_interval_ms", 1000))
        self._last_key = ""
        self._last_ts = 0.0
        self._cache: Optional[NowPlaying] = None

    def poll(self) -> Optional[NowPlaying]:
        now = time.monotonic()
        # Kороткий TTL: не долбить swaymsg/bus каждые 500мс
        if self._cache is not None and now - self._last_ts < self.poll_ms / 1000.0:
            return self._cache
        self._last_ts = now
        result: Optional[NowPlaying] = None
        for det in (self.mpris, self.window):
            if det is None or not det.available():
                continue
            np = det.get_now_playing()
            if np is not None and (np.playing or result is None):
                result = np
                if np.playing:
                    break
        if result is not None:
            key = result.key()
            if key != self._last_key:
                log.info("Now playing [%s]: %s (%s)", result.source, result.title, result.artist or "—")
                self._last_key = key
            # Оценка позиции для браузерных источников (без точного синхрона)
            if result.position_s == 0.0 and result.playing:
                if key == getattr(self, "_prev_key", ""):
                    result.position_s = getattr(self, "_prev_pos", 0.0) + self.poll_ms / 1000.0
                self._prev_key, self._prev_pos = key, result.position_s
            else:
                self._prev_key, self._prev_pos = key, result.position_s
        self._cache = result
        return result
