"""Поиск текстов песен через Genius API (библиотека lyricsgenius) + локальный кэш.

Работа в фоновом потоке, чтобы сетевые запросы не блокировали GTK-цикл.
Если lyricsgenius не установлена или токена нет —Graceful деградация: виджет
показывает «Lyrics not found» и только название трека.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import genius_token
from .track import NowPlaying, normalize

log = logging.getLogger("lyric-overlay.lyrics")


@dataclass
class LyricLine:
    text: str
    start_s: float | None = None   # синхронизированные тайминги (если есть)
    end_s: float | None = None


@dataclass
class SongLyrics:
    title: str
    artist: str
    lines: list[LyricLine] = field(default_factory=list)
    synced: bool = False           # True, если у строк есть тайминги
    source_url: str = ""

    def plain(self) -> str:
        return "\n".join(l.text for l in self.lines)


# ---------------------------------------------------------------------------
# Очистка текста Genius
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\s*\[.*\]\s*$")            # [Chorus], [Verse 1: ...]
_GENIUS_FOOTER_RE = re.compile(
    r"^(Genius is the world[s']?.*|Embed.*|Share.*|Latest Lyrics.*|Sign Up.*)$"
)


def parse_plain_lyrics(raw: str) -> list[LyricLine]:
    lines: list[LyricLine] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or _SECTION_RE.match(ln) or _GENIUS_FOOTER_RE.match(ln):
            continue
        lines.append(LyricLine(text=ln))
    return lines


def parse_timed_lyrics(json_payload: dict) -> list[LyricLine]:
    """Разбор response JSON от /timed-lyrics endpoint (линии с таймкодами)."""
    out: list[LyricLine] = []
    lines = json_payload.get("timed_lyrics") or json_payload.get("lines") or []
    for item in lines:
        txt = (item.get("line") or item.get("text") or "").strip()
        if not txt or _SECTION_RE.match(txt):
            continue
        start = item.get("time_ms", item.get("start"))
        end = item.get("end_ms")
        out.append(LyricLine(
            text=txt,
            start_s=(float(start) / 1000.0) if isinstance(start, (int, float)) else None,
            end_s=(float(end) / 1000.0) if isinstance(end, (int, float)) else None,
        ))
    return out


# ---------------------------------------------------------------------------
# Кэш
# ---------------------------------------------------------------------------

class LyricsCache:
    def __init__(self, cache_dir: Path, ttl_days: int = 30):
        self.dir = cache_dir
        self.ttl = ttl_days * 86400
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.warning("Кэш-каталог недоступен: %s", self.dir)

    def _path(self, key: str) -> Path:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]
        return self.dir / f"{h}.json"

    def get(self, key: str) -> Optional[SongLyrics]:
        p = self._path(key)
        try:
            if not p.is_file() or (time.time() - p.stat().st_mtime) > self.ttl:
                return None
            data = json.loads(p.read_text(encoding="utf-8"))
            lines = [LyricLine(**l) for l in data.get("lines", [])]
            if not lines:
                return None
            return SongLyrics(title=data["title"], artist=data["artist"],
                              lines=lines, synced=data.get("synced", False),
                              source_url=data.get("source_url", ""))
        except Exception:
            return None

    def put(self, key: str, lyrics: SongLyrics) -> None:
        p = self._path(key)
        try:
            p.write_text(json.dumps({
                "title": lyrics.title, "artist": lyrics.artist,
                "synced": lyrics.synced, "source_url": lyrics.source_url,
                "lines": [{"text": l.text, "start_s": l.start_s, "end_s": l.end_s}
                          for l in lyrics.lines],
            }, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.debug("cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Genius-клиент
# ---------------------------------------------------------------------------

class GeniusClient:
    def __init__(self, cfg: dict):
        lyr_cfg = cfg.get("lyrics", {})
        self.token = genius_token(cfg)
        self.timeout = float(lyr_cfg.get("fetch_timeout_s", 8))
        self.cache = LyricsCache(Path(lyr_cfg.get("cache_dir", "~/.cache/lyric-overlay")).expanduser())
        self._genius = None
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self.available = self._init_genius()

    def _init_genius(self) -> bool:
        if not self.token:
            log.warning("GENIUS_TOKEN не задан — поиск текстов будет ограничен "
                        "(без токена доступ к API недоступен)")
            return False
        try:
            import lyricsgenius
            self._genius = lyricsgenius.Genius(
                self.token, timeout=self.timeout, remove_section_headers=True)
            self._genius.verbose = False
            return True
        except ImportError:
            log.error("lyricsgenius не установлен (pip install lyricsgenius)")
            return False
        except Exception as exc:
            log.error("Ошибка инициализации Genius: %s", exc)
            return False

    # -- публичный API -------------------------------------------------------
    def request(self, np: NowPlaying,
                on_ready: Callable[[NowPlaying, Optional[SongLyrics]], None]) -> None:
        """Неблокирующий загрузка: запускает поток, если текста ещё нет в кэше."""
        cached = self.cache.get(np.key())
        if cached is not None:
            on_ready(np, cached)
            return
        with self._lock:
            if np.key() in self._inflight:
                return
            self._inflight.add(np.key())
        threading.Thread(target=self._worker, args=(np, on_ready),
                         daemon=True, name="genius-fetch").start()

    # -- рабочий поток ---------------------------------------------------------
    def _worker(self, np: NowPlaying,
                on_ready: Callable[[NowPlaying, Optional[SongLyrics]], None]) -> None:
        lyrics: Optional[SongLyrics] = None
        try:
            lyrics = self._fetch(np)
            if lyrics is not None:
                self.cache.put(np.key(), lyrics)
        except Exception as exc:
            log.warning("Genius fetch error for %r: %s", np.title, exc)
        finally:
            with self._lock:
                self._inflight.discard(np.key())
        on_ready(np, lyrics)

    def _fetch(self, np: NowPlaying) -> Optional[SongLyrics]:
        if self._genius is None:
            return None
        query = f"{np.artist} {np.title}".strip() if np.artist else np.title
        song = None
        try:
            song = self._genius.search_song(title=np.title, artist=np.artist) \
                if np.artist else self._genius.search_song(title=np.title)
        except Exception:
            pass
        if song is None:
            # второй шанс — общий поиск по строке
            try:
                results = self._genius.search_tracks(query, limit=5)
                for r in results.get("hits", []):
                    t = r.get("track") or {}
                    if t.get("title"):
                        song = self._genius.get_song(t.get("url"))
                        break
            except Exception:
                song = None
        if song is None:
            return None
        lines = parse_plain_lyrics(song.lyrics or "")
        timed: list[LyricLine] = []
        # Пробуем вытащить синхронизированный текст из internal API
        try:
            resp = self._genius.request(
                "get", f"tracks/{song.id}/lyrics",
                params={"format": "json"})
            payload = json.loads(resp) if isinstance(resp, str) else resp
            if isinstance(payload, dict):
                tl = payload.get("response", payload)
                timed = parse_timed_lyrics(tl)
        except Exception:
            timed = []
        synced = len(timed) > 0
        return SongLyrics(
            title=song.title or np.title,
            artist=song.artist or np.artist,
            lines=timed if synced else lines,
            synced=synced,
            source_url=getattr(song, "url", ""),
        )
