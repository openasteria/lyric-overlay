#!/usr/bin/env bash
# Установка зависимостей для Debian / Kali Linux / Ubuntu (Wayland + SwayWM).
set -euo pipefail

echo "[1/3] Системные пакеты (GTK4, layer-shell, GObject bindings, шрифты)..."
sudo apt update
sudo apt install -y \
    python3 python3-pip python3-venv \
    python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
    libgtk-4-1 libgirepository-1.0-1 gobject-introspection \
    gir1.2-gtklayershell-4.0 || echo "  ! gir1.2-gtklayershell-4.0 недоступен — см. README (gtk4-layer-shell из PPA/snap)"
sudo apt install -y \
    layershell || true                       # имя пакета различается по релизам
sudo apt install -y \
    sway waybar fonts-inter fontconfig \
    dbus gdbus busctl || sudo apt install -y dbus-x11

echo "[2/3] Python venv + pip-зависимости..."
cd "$(dirname "$0")/.."
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -e ".[mpris]"        # lyricsgenius, PyYAML, dbus-fast

echo "[3/3] Шрифт Figtree..."
mkdir -p ~/.local/share/fonts/Figtree
if compgen -G "fonts/Figtree/*.ttf" > /dev/null; then
    cp -v fonts/Figtree/*.ttf ~/.local/share/fonts/Figtree/
else
    echo "  Figtree не найден в fonts/Figtree — скачайте с https://figma.com/fonts (SIL OFL)"
fi
fc-cache -f >/dev/null && fc-list | grep -i figtree || echo "  (шрифт не зарегистрирован — будет fallback Inter/Sans)"

echo ""
echo "Готово. Запуск:"
echo "  export GENIUS_TOKEN='ваш_токен'"
echo "  .venv/bin/lyric-overlay"
