# 🎵 Lyric Overlay — виджет текстов песен для Linux + Wayland (SwayWM)

Угловой оверлей-«пилюля», показывающий **текущую строку текста песни** поверх всех
окон. Дизайн строго по макету Figma: иконка 38×36 + динамическая текстовая область,
тёмный фон `#1e1e1e`, скругление 5px, шрифт **Figtree 14px**, активная строка белая,
неактивная — серая `#888`. Формат строки: **«Название песни, текущая строка … следующая»**
— *без имени исполнителя*.

```
┌──────────────────────────────────────────────┐   ← левый верхний угол экрана
│ ♪ │ Bohemian Rhapsody, Is this the real life… │      (layer-shell overlay)
└──────────────────────────────────────────────┘
 38px   ↑ dynamic width (min 146px), height 36px, radius 5px
```

## Возможности

| Источник музыки | Как определяется трек |
|---|---|
| YouTube (Firefox/Chromium) | заголовок окна через `swaymsg -t get_tree` + regex |
| SoundCloud (браузер) | аналогично, паттерны настраиваются в конфиге |
| mpv / yt-dlp | MPRIS-интерфейс mpv или заголовок окна `MPV (file.mp4)` |
| Любой MPRIS-плеер (Spotify, cmus,…) | D-Bus `org.mpris.MediaPlayer2.*` |
| Приоритет источника звука | PulseAudio/PipeWire (`pactl` / `wpctl`) — чей поток активен |

* Тексты через **Genius API** (`lyricsgenius`), локальный кэш `~/.cache/lyric-overlay`.
* Если у трека есть тайминги (synced lyrics) — точная активная строка по позиции
  воспроизведения; если позиция доступна только приблизительно (браузер) —
  равномерная эвристика; если синхронизация невозможна — **весь текст с прокруткой**.
* Только текст, **никаких видео-превью**.
* **Waybar**: модуль `custom/lyric` показывает «♪ название», клик сворачивает/разворачивает оверлей.
* Окно — **wlr-layer-shell** (gtk4-layer-shell), слой `overlay`, якорь top-left: поверх всего,
  не перехватывает клавиатуру, прозрачный фон вокруг.

## Структура проекта

```
lyric-overlay/
├── lyric_overlay/          # Python 3.10+ пакет
│   ├── main.py             # цикл приложения (tick → detect → lyrics → render)
│   ├── config.py           # YAML/JSON конфиг + дефолты
│   ├── detection.py        # MPRIS (D-Bus/gdbus/busctl) + заголовки окон Sway + pactl/wpctl
│   ├── lyrics.py           # Genius API (lyricsgenius) + кэш + фоновые потоки
│   ├── sync.py             # выбор активной строки / прокрутка fallback
│   ├── widget.py           # GTK4 + GtkLayerShell окно-оверлей
│   ├── waybar.py           # файл состояния для waybar custom-модуля
│   └── track.py            # NowPlaying + очистка названий (убираем "Official Video" и пр.)
├── styles/overlay.css      # CSS виджета (цвета/шрифт/radius по Figma)
├── assets/icon.svg         # иконка: белый круг + чёрная нота, radius 5px
├── config/config.yaml      # основной конфиг
├── config/waybar-config-snippet.json
├── scripts/install-deps.sh # установка зависимостей (Debian/Kali)
├── scripts/waybar-module.sh
├── scripts/lyric-overlay.service  # user systemd unit
└── fonts/Figtree/          # положить .ttf шрифта Figtree сюда (OFL, free)
```

## Установка

### 1. Системные пакеты (Debian / Kali / Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv \
    python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
    dbus gdbus busctl fontconfig fonts-inter sway waybar
# gtk4-layer-shell (привязки LayerShellGtk 4):
sudo apt install -y gir1.2-gtklayershell-4.0 || {
    # если пакета нет — соберите из source (быстро):
    sudo apt install -y git cmake build-essential libgtk-4-dev
    git clone https://github.com/wmww/gtk4-layer-shell && cd gtk4-layer-shell
    meson setup build --prefix=/usr && ninja -C build && sudo ninja -C build install
}
```

### 2. Python

```bash
git clone <repo> && cd lyric-overlay
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[mpris]"          # lyricsgenius, PyYAML, dbus-fast
# или без venv (системный python + gi из apt):
pip install lyricsgenius pyyaml dbus-fast requests
```

### 3. Шрифт Figtree (по макету)

Скачайте [Figtree](https://fonts.google.com/specimen/Figtree) (OFL, бесплатно) и:

```bash
mkdir -p ~/.local/share/fonts/Figtree
cp fonts/Figtree/*.ttf ~/.local/share/fonts/Figtree/
fc-cache -f
```

Без шрифта будет аккуратный fallback (Inter → Cantarell → Sans).

### 4. Genius API токен

Получите токен: <https://genius.com/api-tools/new-account-and-application>

```bash
export GENIUS_TOKEN="xxxx"          # или впишите в config/config.yaml → lyrics.genius_token
```

## Запуск

```bash
lyric-overlay                      # GUI-оверлей (layer-shell окно в углу)
lyric-overlay --headless -v        # отладка без GUI: детект + тексты + waybar state
lyric-overlay --once               # один тик: напечатать, что играет и строка текста
lyric-overlay -c my.yaml
```

Автозапуск в Sway (`~/.config/sway/config`):

```
exec_always --no-startup-id $HOME/lyric-overlay/.venv/bin/lyric-overlay
# хоткей свернуть/развернуть:
bindsym $mod+Shift+l exec touch $HOME/.local/state/lyric-overlay/toggle
```

Или systemd user unit: `scripts/lyric-overlay.service`
(`systemctl --user enable --now lyric-overlay`).

## Интеграция с Waybar

В `~/.config/waybar/config` добавьте модуль (готовый сниппет —
`config/waybar-config-snippet.json`):

```json
"modules-left": ["sway/workspaces", "custom/lyric"],
"custom/lyric": {
  "format": "{}",
  "exec": "$HOME/.local/bin/waybar-module.sh",
  "restart-interval": 1,
  "return-type": "json",
  "on-click": "$HOME/.local/bin/waybar-module.sh --toggle",
  "tooltip-format": "{tooltip}"
}
```

Скопируйте скрипт: `cp scripts/waybar-module.sh ~/.local/bin/ && chmod +x ~/.local/bin/waybar-module.sh`.
Модуль покажет `♪ Название трека`; клик разворачивает/сворачивает оверлей
(через файл-флаг toggle, который приложение опрашивает каждый тик).

CSS для waybar (опционально):

```css
#custom-lyric.playing  { color: #ffffff; }
#custom-lyric.paused   { color: #888888; }
#custom-lyric.idle     { color: #555555; }
```

## Конфигурация (`config/config.yaml`)

Ключевые параметры — см. комментарии в файле:

* `widget.anchor_corner` — положение (`top-left` по умолчанию);
* `widget.icon_size/text_min_width/text_max_width/corner_radius/icon_gap/height` — геометрия по Figma;
* `widget.colors.*` — `#1e1e1e`, белый/`#888`;
* `widget.font.family` — `Figtree`;
* `lyrics.scroll_when_unsynced` — прокрутка всего текста при невозможности синхронизации;
* `detection.window_title.patterns` — regex для YouTube/SoundCloud/mpv/браузеров;
* `waybar.state_file` — JSON-состояние для custom-модуля.

Поддержка JSON-конфига: переименуйте `config.yaml` → `config.json` (PyYAML не нужен).

## Как это работает (поток данных)

```
swaymsg get_tree ─┐
D-Bus MPRIS     ──┼─► TrackDetector.poll() ─► NowPlaying{title, artist*, playing, position}
pactl/wpctl     ──┘        │                       (*artist — только для поиска Genius,
                           ▼                         в виджете НЕ показывается)
                  GeniusClient.request()  ─► SongLyrics (кэш/сеть, фоновый поток)
                           │
              synced?      ├─ yes ► LineSelector.active_index(position)  (бинарный поиск)
                           └─ no  ► равномерная эвристика / Scroller (прокрутка всего текста)
                           ▼
              GTK4 layer-shell overlay:  «Title, active line … next»
                           ▼
              WaybarState.write(): {"text":"♪ Title","class":"playing"}
```

## Troubleshooting

| Проблема | Решение |
|---|---|
| `No such interface 'LayerShell'` | не установлен gtk4-layer-shell (см. шаг 1). Оверлей запустится обычным окном. |
| Ничего не детектится в браузере | убедитесь, что `swaymsg -t get_tree` работает; подправьте `detection.window_title.patterns` под свой формат заголовков |
| `GENIUS_TOKEN не задан` | получите токен на genius.com/api-tools |
| Нет обложек mpris artUrl http | GNOME/некоторые плееры дают `file://` — поддерживается |
| Виджет перекрывает уведомления | поменяйте `widget.layer: top` или corner |
| Кали/Deb: `gi` не находится в venv | используйте системный python: `python3 -m lyric_overlay.main` без venv, либо `apt install python3-gi` и запускайте тем же интерпретатором |

## Лицензия

MIT. Шрифт Figtree — SIL Open Font License (не включён в репозиторий, скачайте сами).
Иконка `assets/icon.svg` — по мотивам макета Figma.

## 🚀 Быстрый запуск (одной командой, без автозапуска)

```bash
curl -fsSL https://raw.githubusercontent.com/openasteria/lyric-overlay/master/scripts/run.sh | bash
```

Виджет запустится прямо в этом терминале — **Ctrl+C** мгновенно его закрывает.
Ничего не добавляется в autostart/systemd. Скрипт скачивает репозиторий в
`~/.local/share/lyric-overlay`, при первом запуске ставит зависимости, дальше
только обновляет и запускает. Токен Genius: `GENIUS_TOKEN='токен' curl -fsSL ... | bash -s --`
или экспортируйте `GENIUS_TOKEN` перед запуском.
