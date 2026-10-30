"""GTK4-виджет оверлея (layer-shell окно в углу экрана поверх всего).

Стек: PyGObject (gi) + Gtk 4 + LayerShellGtk (gtk4-layer-shell),
который предоставляет протокол wlr-layer-shell-unstable-v1 — то, что нужно
для SwayWM. Позиционирование в левом верхнем углу — через anchors+margin.

Дизайн строго по макету Figma:
    [иконка 38×36]  gap 10px  [текст 146×36, растёт динамически]
    высота строки 36px, corner radius 5px, фон #1e1e1e,
    Figtree 14px, активная строка белая, неактивная — #888.

CSS вынесен в styles/overlay.css и подгружается в рантайме.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("lyric-overlay.widget")

try:
    import gi
    gi.require_version("Gtk", "4.0")
    try:
        gi.require_version("LayerShell", "4")   # gtk4-layer-shell
        from gi.repository import LayerShell    # noqa: F401
        HAS_LAYERSHELL = True
    except ValueError:
        HAS_LAYERSHELL = False
    from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf, Gio
except (ImportError, ValueError) as exc:  # pragma: no cover
    raise RuntimeError(
        "GTK4/GObject bindings недоступны. Установите:\n"
        "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 "
        "libgtk-4 layer-shell-qt gir1.2-gtklayershell-4.0\n"
        "(или pip install PyGObject)"
    ) from exc


CSS_CLASS_ROOT = "lyric-overlay"

_ANCHORS = {
    "top-left":     (True,  True,  False, False),   # top, left, bottom, right
    "top-right":    (True,  False, False, True),
    "bottom-left":  (False, True,  True,  False),
    "bottom-right": (False, False, True, True),
}

_LAYERS = {"background": 0, "bottom": 1, "top": 2, "overlay": 3}


def _load_css(widget_window: Gtk.Widget, repo_root: Path) -> None:
    css_path = repo_root / "styles" / "overlay.css"
    if not css_path.is_file():
        css_path = Path(__file__).resolve().parent.parent / "styles" / "overlay.css"
    provider = Gtk.CssProvider()
    try:
        if hasattr(provider, "load_from_path"):
            provider.load_from_path(str(css_path))
        else:
            provider.load_from_data(css_path.read_bytes())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10,
        )
        log.debug("CSS loaded from %s", css_path)
    except Exception as exc:
        log.warning("Не удалось загрузить CSS (%s): %s — использую встроенный", css_path, exc)
        fallback = f"""
        .{CSS_CLASS_ROOT} {{ background: transparent; }}
        .{CSS_CLASS_ROOT} .pill {{
            background: #1e1e1e; border-radius: 5px; padding: 0px;
        }}
        .{CSS_CLASS_ROOT} .active-line  {{ color: #ffffff; font-weight: 600; }}
        .{CSS_CLASS_ROOT} .inactive-line {{ color: #888888; }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(fallback.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)


class OverlayWindow:
    """Окно-оверлей: иконка + текстовая область («Title, active line …next» )."""

    def __init__(self, cfg: dict, on_toggle_visibility=None):
        self.cfg = cfg["widget"]
        colors = self.cfg["colors"]
        font = self.cfg["font"]

        # ---- CSS ----------------------------------------------------------
        base_css = f"""
        .{CSS_CLASS_ROOT}              {{ background: transparent; }}
        .{CSS_CLASS_ROOT} .pill        {{
            background: {colors['background']};
            border-radius: {self.cfg['corner_radius']}px;
        }}
        .{CSS_CLASS_ROOT} .icon-box    {{
            background: {colors['icon_fallback_bg']};
            border-radius: {self.cfg['corner_radius']}px;
            min-width:  {self.cfg['icon_size']}px;
            min-height: {self.cfg['height']}px;
        }}
        .{CSS_CLASS_ROOT} .icon-box image {{
            border-radius: {self.cfg['corner_radius']}px;
        }}
        .{CSS_CLASS_ROOT} .text-area   {{
            min-height: {self.cfg['height']}px;
            padding: 0 12px 0 0;
        }}
        .{CSS_CLASS_ROOT} label {{
            font-family: "{font['family']}", "{font['fallback_family']}";
            font-size: {font['size_px']}px;
            color: {colors['text_inactive']};
        }}
        .{CSS_CLASS_ROOT} .active-line   {{ color: {colors['text_active']}; }}
        .{CSS_CLASS_ROOT} .inactive-line {{ color: {colors['text_inactive']}; }}
        """
        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_data(base_css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_SETTINGS)
        _load_css(None, Path(__file__).resolve().parent.parent)

        # ---- Окно ----------------------------------------------------------
        self.window = Gtk.ApplicationWindow()
        self.window.set_title("lyric-overlay")
        self.window.add_css_class(CSS_CLASS_ROOT)
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_default_size(-1, self.cfg["height"])

        if HAS_LAYERSHELL:
            LayerShell.init()
            LayerShell.set_layer(self.window,
                                 _LAYER_ENUM[self.cfg.get("layer", "overlay")])
            top, left, bottom, right = _ANCHORS.get(
                self.cfg.get("anchor_corner", "top-left"), _ANCHORS["top-left"])
            LayerShell.set_anchor(self.window, LayerShell.Edge.TOP, top)
            LayerShell.set_anchor(self.window, LayerShell.Edge.LEFT, left)
            LayerShell.set_anchor(self.window, LayerShell.Edge.BOTTOM, bottom)
            LayerShell.set_anchor(self.window, LayerShell.Edge.RIGHT, right)
            LayerShell.set_margin(self.window, LayerShell.Edge.TOP,
                                  int(self.cfg["margin_y"]))
            LayerShell.set_margin(self.window, LayerShell.Edge.LEFT,
                                  int(self.cfg["margin_x"]))
            LayerShell.set_margin(self.window, LayerShell.Edge.BOTTOM,
                                  int(self.cfg["margin_y"]))
            LayerShell.set_margin(self.window, LayerShell.Edge.RIGHT,
                                  int(self.cfg["margin_x"]))
            LayerShell.set_exclusive_zone(self.window, int(self.cfg["exclusive_zone"]))
            ki = str(self.cfg.get("keyboard_interactive", "none"))
            mode = getattr(LayerShell.KeyboardMode,
                           "KEYBOARD_MODE_" + ki.upper().replace("-", "_"),
                           LayerShell.KeyboardMode.NONE)
            LayerShell.set_keyboard_mode(self.window, mode)
        else:
            log.warning("gtk4-layer-shell недоступен — окно будет обычным "
                        "(установите libgtk-4-layer-shell / gir1.2-gtklayershell-4.0)")
            self.window.set_keep_above(True)
            self.move_mock()

        # ---- Контент --------------------------------------------------------
        self.pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=self.cfg["icon_gap"])
        self.pill.add_css_class("pill")

        # Иконка 38×36 (скругление 5px делает CSS); белый круг с чёрной нотой —
        # из assets/icon.svg; при наличии обложки трека подставляем её.
        self.icon_image = Gtk.Image()
        self.icon_box = Gtk.Box()
        self.icon_box.add_css_class("icon-box")
        self.icon_box.set_size_request(self.cfg["icon_size"], self.cfg["height"])
        self.icon_box.append(self.icon_image)

        # Текстовая область: три inline-label'а в одной строке
        self.text_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.text_area.add_css_class("text-area")
        self.lbl_title = Gtk.Label(xalign=0)          # «Название песни,»
        self.lbl_title.add_css_class("active-line")
        self.lbl_line = Gtk.Label(xalign=0)           # активная строка — белая
        self.lbl_line.add_css_class("active-line")
        self.lbl_next = Gtk.Label(xalign=0)           # следующая часть — серая
        self.lbl_next.add_css_class("inactive-line")
        for lbl in (self.lbl_title, self.lbl_line, self.lbl_next):
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_max_width_chars(60)
            lbl.set_valign(Gtk.Align.CENTER)
            lbl.set_lines(1)
            self.text_area.append(lbl)

        self.pill.append(self.icon_box)
        self.pill.append(self.text_area)
        self.window.set_child(self.pill)

        # Прозрачность фона окна (сам виджет opacity 100%)
        a = float(self.cfg.get("opacity", 1.0))
        if a < 1.0:
            ov = Gtk.Overlay(child=self.pill)
            self.window.set_child(ov)

        self.on_toggle_visibility = on_toggle_visibility
        self._visible = True

        # ЛКМ по виджету — свернуть/развернуть (полезно вместе с Waybar)
        gesture = Gtk.GestureClick.new()
        gesture.connect("pressed", self._on_click)
        self.pill.add_controller(gesture)

        self._set_default_icon()

    # -----------------------------------------------------------------------
    def move_mock(self, *_):  # без layer-shell просто ставим в угол максимально
        try:
            mon = Gdk.Display.get_default().get_monitor(0)
            g = mon.get_geometry()
            self.window.move(g.x + 12, g.y + 12)
        except Exception:
            pass

    def _set_default_icon(self) -> None:
        svg = (Path(__file__).resolve().parent.parent / "assets" / "icon.svg")
        size = int(self.cfg["icon_size"]) - 2
        if svg.is_file():
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(str(svg), size, size)
                self.icon_image.set_from_paintable(
                    Gdk.Texture.new_for_pixbuf(pb))
                return
            except Exception as exc:
                log.debug("default icon load failed: %s", exc)
        self.icon_image.set_from_icon_name("audio-x-generic-symbolic")

    def set_artwork(self, url: str) -> None:
        """Обложка трека вместо иконки приложения (mpris artUrl / http / file)."""
        if not url:
            self._set_default_icon()
            return
        size = int(self.cfg["icon_size"]) - 2

        def done(tex):
            if tex is not None:
                self.icon_image.set_from_paintable(tex)

        try:
            if url.startswith("file://") or url.startswith("/"):
                path = url.removeprefix("file://")
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
                done(Gdk.Texture.new_for_pixbuf(pb))
            elif url.startswith(("http://", "https://")):
                f = Gio.File.new_for_uri(url)
                f.load_contents_async(None, lambda src, res, data=None: self._art_http_done(src, res, done))
        except Exception as exc:
            log.debug("artwork load failed (%s): %s", url, exc)
            self._set_default_icon()

    def _art_http_done(self, src, res, cb) -> None:
        try:
            _ok, stream = src.load_contents_finish(res)
            loader = GdkPixbuf.PixbufLoader.new()
            loader.set_size(int(self.cfg["icon_size"]) - 2,
                            int(self.cfg["height"]) - 2)
            loader.write(stream)
            loader.close()
            cb(Gdk.Texture.new_for_pixbuf(loader.get_pixbuf()))
        except Exception:
            cb(None)
            self._set_default_icon()

    # -----------------------------------------------------------------------
    def update_text(self, title: str, active_line: str, next_part: str,
                    width_ratio: float = 1.0) -> None:
        """title — «Название песни,», active_line — белая, next_part — серая."""
        show_prefix = bool(self.cfg.get("show_title_prefix", True))
        sep = self.cfg.get("title_separator", ", ")
        self.lbl_title.set_text(f"{title}{sep}" if (show_prefix and title) else "")
        self.lbl_title.set_visible(bool(show_prefix and title))
        self.lbl_line.set_text(active_line)
        self.lbl_next.set_text(next_part)
        self.lbl_next.set_visible(bool(next_part))
        # Динамическая ширина текстовой области: min 146 → max text_max_width
        est = max(self.cfg["text_min_width"],
                  min(self.cfg["text_max_width"],
                      int((len(title) + len(active_line) + len(next_part)) * 7.2 * width_ratio)))
        self.text_area.set_size_request(est, self.cfg["height"])

    def set_status_dim(self, dim: bool) -> None:
        """Когда ничего не играет / пауза — вся строка серая (#888)."""
        cls = "inactive-line" if dim else "active-line"
        self.lbl_title.remove_css_class("active-line"); self.lbl_title.remove_css_class("inactive-line")
        self.lbl_line.remove_css_class("active-line"); self.lbl_line.remove_css_class("inactive-line")
        self.lbl_title.add_css_class(cls)
        self.lbl_line.add_css_class(cls)

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        if visible:
            self.window.present()
        else:
            self.window.hide()

    @property
    def visible(self) -> bool:
        return self._visible

    def _on_click(self, gesture, n_press, x, y) -> None:
        if self.on_toggle_visibility:
            self.on_toggle_visibility()

    def realize(self) -> None:
        self.window.present()


# enum-маппинг слоя (значение int → enum LayerShell)
def _mk_layer_enum():
    m = {}
    for name, val in (("background", 0), ("bottom", 1), ("top", 2), ("overlay", 3)):
        try:
            m[val] = getattr(LayerShell.Layer, f"LAYER_{name.upper()}")
        except AttributeError:
            m[val] = LayerShell.Layer.OVERLAY
    return m

try:
    _LAYER_ENUM = _mk_layer_enum()
except NameError:      # LayerShell не импортирован — не используется
    _LAYER_ENUM = {}
