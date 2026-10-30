"""Выбор активной строки текста и режим прокрутки при отсутствии синхронизации.

Стратегия:
  * Если у текста есть тайминги (synced) и доступна позиция трека —
    бинарный поиск строки по времени.
  * Иначе — эвристика «строка ≈ время»: равномерно распределяем строки по
    длительности трека (или по оценке 3.5 с/строку).
  * Если длительность неизвестна и синхронизация невозможна — показываем
    весь текст с плавной прокруткой (scroll_when_unsynced).
"""

from __future__ import annotations

import math
from typing import Optional

from .lyrics import SongLyrics
from .track import NowPlaying


class LineSelector:
    """Сопоставляет позицию воспроизведения со строкой текста."""

    def __init__(self, np: NowPlaying, lyrics: SongLyrics):
        self.np = np
        self.lyrics = lyrics
        self.count = len(lyrics.lines)
        # Средняя длительность строки для несинхронизированного режима
        if lyrics.synced:
            self.per_line_s = 0.0
        elif np.length_s > 0 and self.count > 0:
            self.per_line_s = np.length_s / self.count
        else:
            self.per_line_s = 3.5  # оценка: ~3.5 секунды на строку

    # -- активная строка ------------------------------------------------------
    def active_index(self, position_s: float) -> int:
        if self.count == 0:
            return -1
        if self.lyrics.synced:
            lo, hi = 0, self.count - 1
            ans = 0
            while lo <= hi:
                mid = (lo + hi) // 2
                start = self.lyrics.lines[mid].start_s or 0.0
                if start <= position_s:
                    ans = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            return ans
        # Эвристика по равномерному распределению
        idx = int(position_s / max(self.per_line_s, 0.1))
        return min(max(idx, 0), self.count - 1)

    def can_sync(self, np: NowPlaying) -> bool:
        """True, если можем уверенно выбирать строку по позиции."""
        if not np.playing:
            return False
        if self.lyrics.synced:
            return True
        # Для MPRIS-плееров позиция известна точно; для браузеров — оценка
        return np.source.startswith("mpris:") or np.length_s > 0


# ---------------------------------------------------------------------------
# Прокрутка всего текста (fallback-режим)
# ---------------------------------------------------------------------------

class Scroller:
    """Плавная горизонтальная прокрутка длинного текста по символам."""

    def __init__(self, step_chars: float = 2.0, pause_ticks: int = 6):
        self.step = step_chars
        self.pause_ticks = pause_ticks
        self._offset = 0.0
        self._pause = 0
        self._text_len = 0

    def reset(self, text_len: int) -> None:
        self._offset = 0.0
        self._pause = 0
        self._text_len = text_len

    def tick(self) -> float:
        """Сдвинуть окно просмотра; пауза на старте/конце."""
        if self._text_len <= 0:
            return 0.0
        if self._pause > 0:
            self._pause -= 1
        else:
            self._offset += self.step
            if self._offset >= max(self._text_len - 1, 1):
                self._offset = 0.0
                self._pause = self.pause_ticks
        return self._offset

    def window(self, full_text: str, width: int) -> tuple[str, bool]:
        """Возвращает (фрагмент шириной ~width символов, конец_ли? )."""
        off = int(math.floor(self._offset))
        if off >= len(full_text):
            off = 0
        frag = full_text[off:off + width]
        at_end = off + width >= len(full_text)
        return frag, at_end
