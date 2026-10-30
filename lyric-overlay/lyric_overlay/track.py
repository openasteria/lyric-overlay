"""Структуры данных «что сейчас играет» и очистка названий треков."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class NowPlaying:
    """Текущий трек. title — БЕЗ исполнителя (требование пользователя)."""

    title: str = ""
    artist: str = ""            # используется только для поиска на Genius
    source: str = ""            # mpris | youtube | soundcloud | mpv | browser
    playing: bool = False
    position_s: float = 0.0     # позиция воспроизведения, сек (если доступна)
    length_s: float = 0.0       # длительность, сек (если доступна)
    artwork_url: str = ""       # локальный file:// или http(s)://
    raw: dict = field(default_factory=dict)

    def key(self) -> str:
        """Уникальный ключ трека для кэша/сравнений."""
        return f"{self.source}|{normalize(self.title)}|{normalize(self.artist)}"

    def __str__(self) -> str:  # pragma: no cover
        return f"NowPlaying({self.source}: {self.title!r} by {self.artist!r}, playing={self.playing})"


# ---------------------------------------------------------------------------
# Очистка заголовков
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = [
    # Просьбы подписаться / ссылки в названиях YouTube/SoundCloud
    r"(?i)\b(subscribe|follow me|stream (now|here)|download|pre[- ]?order|"
    r"official (music )?(video|audio|visualizer|lyric ?video?s?)|lyrics?|"
    r"audio|mv|mv\s*4k|hd|hq|4k|8k|vevo|explicit|clean|feat\.?|ft\.?|"
    r"prod\.?\s+by|beat\s*store|type beat|instrumental)\b.*$",
    r"[（(\[{]\s*(?:official|lyric|audio|visualizer|mv|hd|hq|4k|live|remaster(ed)?|"
    r"mono|stereo|expanded|deluxe|bonus|feat\.?|ft\.?).{0,60}[）)\]}]",
    r"#\w+",
    r"(?i)\|\s*(youtube|soundcloud|spotify|apple music|tidal|deezer)\s*$",
    r"(?i)-\s*(youtube|soundcloud|spotify)\s*$",
]
_NOISE_RE = [re.compile(p) for p in _NOISE_PATTERNS]

_TRACK_PREFIX_RE = re.compile(r"^\s*\d{1,2}\s*[.)\-:]\s+")           # "1. Song Name"
_MULTI_DASH_RE = re.compile(r"\s*[–—-]{1,3}\s*")                      # склеить тире
_WS_RE = re.compile(r"\s+")


_DASH_SPLIT_RE = re.compile(r"\s+[–—-]\s+")


def clean_title(raw: str) -> str:
    """Приводит заголовок окна/MPRIS к «названию песни без исполнителя».

    Примеры:
        "Queen – Bohemian Rhapsody (Official Video) - YouTube - Mozilla Firefox"
            -> "Bohemian Rhapsody"
        "Bohemian Rhapsody (Official Video)"      -> "Bohemian Rhapsody"
        "1. Bohemian Rhapsody [HD]"               -> "Bohemian Rhapsody"
    """
    if not raw:
        return ""
    t = raw.strip()
    # Отрезаем хвосты проигрывателей/браузеров, если они остались в строке
    for tail in (" - YouTube", " — YouTube", " - SoundCloud", " — SoundCloud",
                 " - Mozilla Firefox", " - Google Chrome", " - Chromium"):
        idx = t.rfind(tail)
        if idx > 0 and idx == len(t) - len(tail):
            t = t[:idx].strip()
    # Снимаем шум («(Official Video)», «#tag», хвосты «| YouTube» и т.п.)
    for rx in _NOISE_RE:
        t = rx.sub("", t)
    t = _TRACK_PREFIX_RE.sub("", t)
    t = t.strip(" \t\r\n-–—·•|[](){}")
    # Если после очистки осталось «Artist – Title» — берём последнюю часть
    parts = [p.strip() for p in _DASH_SPLIT_RE.split(t) if p.strip()]
    if len(parts) >= 2:
        t = parts[-1]
    t = _WS_RE.sub(" ", t).strip()
    return t


def split_artist_title(text: str) -> tuple[str, str]:
    """Пытается разбить «Artist - Title» на пару. Возвращает (artist, title).

    Если разделитель не найден — artist пустой, title = text.
    """
    parts = _MULTI_DASH_RE.split(text, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].strip(), parts[1].strip()
    return "", text.strip()


def normalize(s: str) -> str:
    """Нормализация для сравнения/кэша: нижний регистр, без пунктуации."""
    s = s.lower()
    s = re.sub(r"[’'`´]", "", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = _WS_RE.sub(" ", s).strip()
    return s


def filename_to_title(name: str) -> str:
    """'01 - Artist - Song.mp3' -> 'Song' (для mpv/локальных файлов).

    Все «–/-»-сегменты очищаются от шума; последний непустой сегмент
    считается названием трека (предпоследний — исполнителем).
    """
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)   # расширение
    name = name.replace("_", " ")
    parts = [clean_title(p) for p in _DASH_SPLIT_RE.split(name)]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) >= 2:
        return parts[-1]
    # один сегмент без пробельного тире — пробуем классический разбор
    artist, title = split_artist_title(name)
    title = _TRACK_PREFIX_RE.sub("", clean_title(title) or title)
    return title.strip() or name.strip()
