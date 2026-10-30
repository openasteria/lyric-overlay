"""Lyric Overlay — угловой виджет текущей строки текста песни для Linux + Wayland (SwayWM).

Модули:
    config      — загрузка YAML/JSON конфигурации
    track       — общие структуры (NowPlaying) и очистка названий
    detection   — детекция трека: MPRIS (D-Bus) + заголовки окон Sway
    lyrics      — поиск текстов через Genius API (lyricsgenius) с кэшем
    sync        — выбор активной строки / прокрутка при отсутствии синхронизации
    widget      — GTK4 + GtkLayerShell оверлей (layer-shell окно в углу)
    waybar      — запись состояния для модуля Waybar
"""

__version__ = "1.0.0"
__all__ = ["config", "track", "detection", "lyrics", "sync", "widget", "waybar"]
