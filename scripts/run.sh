#!/usr/bin/env bash
# Быстрый запуск без автозапуска: клонирует репозиторий (если нужно),
# ставит зависимости, запускает виджет в этом же терминале.
# Ctrl+C — мгновенное закрытие. Ничего не добавляется в autostart/systemd.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/openasteria/lyric-overlay.git}"
DIR="${LYRIC_OVERLAY_DIR:-$HOME/.local/share/lyric-overlay}"

if [ ! -d "$DIR/.git" ]; then
    echo "[*] Клонирование $REPO_URL -> $DIR"
    git clone "$REPO_URL" "$DIR"
else
    echo "[*] Обновление $DIR"
    git -C "$DIR" pull --ff-only || true
fi

cd "$DIR"

if [ ! -x .venv/bin/lyric-overlay ]; then
    echo "[*] Установка зависимостей (apt + venv)..."
    ./scripts/install-deps.sh
fi

# токен Genius можно передать так: GENIUS_TOKEN='xxx' ./scripts/run.sh
echo "[*] Запуск lyric-overlay (Ctrl+C — остановить)..."
exec .venv/bin/lyric-overlay "$@"
