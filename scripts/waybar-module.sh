#!/usr/bin/env bash
# Скрипт для модуля Waybar:  "custom/lyric" -> "exec": ".../waybar-module.sh"
# Печатает JSON-состояние, которое пишет lyric-overlay (мгновенно, без сети).
# Клик по модулю (on-click) трогает файл-флаг — оверлей сворачивается/разворачивается.

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/lyric-overlay/waybar.json"
TOGGLE="${XDG_STATE_HOME:-$HOME/.local/state}/lyric-overlay/toggle"

case "${1:-}" in
    --toggle)
        mkdir -p "$(dirname "$TOGGLE")"
        touch "$TOGGLE"
        exit 0
        ;;
esac

if [ -f "$STATE" ]; then
    cat "$STATE"
else
    echo '{"text":"♪","class":"idle","tooltip":"lyric-overlay: not running"}'
fi
