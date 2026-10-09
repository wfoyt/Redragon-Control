"""Native GTK 4 / libadwaita front end for Redragon Control.

All hardware and configuration work goes through Controller.  GTK widgets are
only touched on the main thread; device operations run on a worker thread.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__
from .core import Controller  # noqa: E402
from .config import MODES, NATIVE_COLORS, validate_binding  # noqa: E402
from .errors import ControlError  # noqa: E402
from .effects import MODE_LABELS, NATIVE_EFFECTS  # noqa: E402
from .preview import EFFECT_DESCRIPTIONS, REACTIVE_MODES, sample  # noqa: E402
from .setup import SetupStore, keyboard_candidates  # noqa: E402


APP_ID = "io.github.redragon.Control"
PRESET_SOURCES = (
    ("KEY_VOLUMEUP", "Wheel up", "Turn the wheel upward"),
    ("KEY_VOLUMEDOWN", "Wheel down", "Turn the wheel downward"),
    ("KEY_MUTE", "Wheel press", "Press the wheel / mute button"),
)
TARGETS = (
    "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE", "KEY_PLAYPAUSE",
    "KEY_NEXTSONG", "KEY_PREVIOUSSONG", "KEY_BRIGHTNESSUP",
    "KEY_BRIGHTNESSDOWN", "KEY_LEFTCTRL+KEY_LEFTALT+KEY_T", "scroll-up",
    "scroll-down", "default", "disabled",
)
TARGET_LABELS = {
    "KEY_VOLUMEUP": "Volume up", "KEY_VOLUMEDOWN": "Volume down",
    "KEY_MUTE": "Mute / unmute", "KEY_PLAYPAUSE": "Play / pause",
    "KEY_NEXTSONG": "Next track", "KEY_PREVIOUSSONG": "Previous track",
    "KEY_BRIGHTNESSUP": "Screen brightness up",
    "KEY_BRIGHTNESSDOWN": "Screen brightness down",
    "KEY_LEFTCTRL+KEY_LEFTALT+KEY_T": "Ctrl + Alt + T",
    "scroll-up": "Scroll up", "scroll-down": "Scroll down",
    "default": "Keep default action", "disabled": "Disable this control",
}

CSS = """
.hero-card { border-radius: 18px; background: alpha(@accent_bg_color, .08); }
.hero-title { font-size: 25px; font-weight: 800; letter-spacing: -.5px; }
.eyebrow { font-size: 10px; font-weight: 800; letter-spacing: 1.5px; }
.section-title { font-size: 22px; font-weight: 800; }
.status-pill { border-radius: 99px; padding: 5px 10px; font-size: 11px; font-weight: 700; background: alpha(@window_fg_color, .07); }
.status-pill.connected { background: alpha(@success_color, .13); color: @success_color; }
.status-pill.demo { background: alpha(@accent_bg_color, .15); color: @accent_color; }
.note-card { border-radius: 12px; padding: 14px; background: alpha(@window_fg_color, .045); }
.note-card.warning { background: alpha(@warning_color, .09); }
.page-content { padding: 24px 30px 30px; }
.device-line { font-size: 12px; }
.key-entry { font-family: monospace; font-size: 12px; }
.keyboard-caption { font-size: 10px; }
"""


def _label(text, css_class=None, *, wrap=False, xalign=0):
    label = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    if css_class:
        label.add_css_class(css_class)
    return label


def _box(orientation=Gtk.Orientation.VERTICAL, spacing=12):
    return Gtk.Box(orientation=orientation, spacing=spacing)


def _button(label=None, icon=None, css_class=None):
    button = Gtk.Button(label=label) if label else Gtk.Button(icon_name=icon)
    if css_class:
        button.add_css_class(css_class)
    return button


def _lighting(config):
    lighting = config.get("lighting", {})
    return lighting if isinstance(lighting, dict) else {}


def _bindings(config):
    bindings = config.get("bindings", {})
    if isinstance(bindings, dict):
        return bindings
    if isinstance(bindings, list):
        return {item["source"]: item["target"] for item in bindings
                if isinstance(item, dict) and "source" in item and "target" in item}
    return {}


class KeyboardPreview(Gtk.DrawingArea):
    """An intentionally illustrative keyboard, never a claimed key map."""

    def __init__(self):
        super().__init__()
        self.set_content_width(420)
        self.set_content_height(155)
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.mode = "rainbow"
        self.color = "#E74957"
        self.brightness = 80
        self.speed = 50
        self.elapsed = 0.0
        self._tick_id = None
        self._animation_start = None
        self._last_frame = 0
        self.set_draw_func(self._draw)
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Illustrative keyboard lighting preview"])

    def configure(self, mode, color, brightness, speed):
        if mode != self.mode:
            self._animation_start = None
            self.elapsed = 0.0
        self.mode, self.color = mode, color
        self.brightness, self.speed = brightness, speed
        if mode in NATIVE_EFFECTS and self._tick_id is None:
            self._tick_id = self.add_tick_callback(self._animate)
        elif mode not in NATIVE_EFFECTS and self._tick_id is not None:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = None
        self.queue_draw()

    def _animate(self, _widget, clock):
        now = clock.get_frame_time()
        if self._animation_start is None:
            self._animation_start = now
        if now - self._last_frame >= 30_000:
            self.elapsed = (now - self._animation_start) / 1_000_000
            self._last_frame = now
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _rounded(ctx, x, y, width, height, radius):
        radius = min(radius, width / 2, height / 2)
        ctx.new_sub_path()
        ctx.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        ctx.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        ctx.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        ctx.close_path()

    def _draw(self, _area, ctx, width, height):
        scale = min(width / 420, height / 155)
        ctx.translate((width - 420 * scale) / 2, (height - 155 * scale) / 2)
        ctx.scale(scale, scale)
        dark = Adw.StyleManager.get_default().get_dark()
        self._rounded(ctx, 9, 15, 402, 127, 13)
        ctx.set_source_rgba(.02, .03, .05, .13 if not dark else .4)
        ctx.fill()
        self._rounded(ctx, 5, 8, 402, 127, 13)
        ctx.set_source_rgb(*((.19, .20, .23) if dark else (.22, .23, .26)))
        ctx.fill()
        self._rounded(ctx, 9, 12, 394, 119, 10)
        ctx.set_source_rgb(.12, .13, .15)
        ctx.fill()
        color = Gdk.RGBA()
        valid_color = self.color if color.parse(self.color) else "#E74957"
        settings = {"mode": self.mode, "color": valid_color,
                    "brightness": self.brightness, "speed": self.speed}

        def key(x, y, w=21, h=17, col=0, label=None):
            rgb = sample(settings, self.elapsed,
                         (x + w / 2 - 17) / 24, (y + h / 2 - 20) / 20)
            self._rounded(ctx, x, y, w, h, 3)
            ctx.set_source_rgba(*rgb, .9)
            ctx.fill()
            self._rounded(ctx, x + 1, y + 1, w - 2, h - 3, 2)
            ctx.set_source_rgb(.20, .21, .24)
            ctx.fill()
            if label:
                ctx.set_source_rgba(*rgb, 1)
                ctx.set_font_size(5.5)
                ctx.move_to(x + 4, y + 9)
                ctx.show_text(label)
            else:
                ctx.set_source_rgba(*rgb, 1)
                ctx.rectangle(x + w / 2 - 2, y + 5, 4, 1.5)
                ctx.fill()

        for row in range(5):
            for col in range(14):
                key(17 + col * 24, 20 + row * 20, col=col,
                    label="esc" if row == 0 and col == 0 else None)
        # A spacebar and modifiers replace the bottom row of regular keycaps.
        ctx.set_source_rgb(.12, .13, .15)
        ctx.rectangle(16, 99, 337, 22)
        ctx.fill()
        for index, (x, w) in enumerate(((17, 29), (49, 29), (81, 29), (113, 121), (237, 29), (269, 29), (301, 29), (333, 20))):
            key(x, 100, w, 17, col=index * 2)
        for row in range(4):
            key(367, 40 + row * 20, 23, 17, col=15)
        self._rounded(ctx, 363, 19, 31, 13, 6)
        ctx.set_source_rgb(.40, .42, .46)
        ctx.fill()
        for x in range(369, 391, 4):
            ctx.set_source_rgba(.1, .1, .12, .7)
            ctx.rectangle(x, 21, 1, 9)
            ctx.fill()


class ControlWindow(Adw.ApplicationWindow):
    def __init__(self, application, controller):
        super().__init__(application=application, title="Redragon Control")
        Gtk.IconTheme.get_for_display(self.get_display()).add_search_path(str(Path(__file__).resolve().parent.parent / "data"))
        Gtk.Window.set_default_icon_name(APP_ID)
        self.controller = controller
        self.state = {}
        self._busy = False
        self._updating = False
        self._device_ids = []
        self._binding_editors = {}
        self.setup_store = SetupStore(controller.store.path)
        self._in_setup = controller.demo or not self.setup_store.completed()
        self._setup_step = 0
        self._setup_bindings = {}
        self._setup_profile_imported = False
        self._setup_import_pending = False
        self.set_default_size(980, 900)
        self.set_size_request(760, 620)

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.toolbar = Adw.ToolbarView()
        self.toasts.set_child(self.toolbar)
        header = Adw.HeaderBar()
        self.toolbar.add_top_bar(header)

        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        self.switcher = switcher
        self.activity = Gtk.Spinner()
        self.activity.set_visible(False)
        header.pack_start(self.activity)
        menu = Gio.Menu()
        for title, action in (("Save Named Profile…", "save-profile"),
                              ("Load Named Profile…", "load-profile"),
                              ("Import Profile…", "import-profile"),
                              ("Export Profile…", "export-profile")):
            menu.append(title, "win." + action)
        section = Gio.Menu()
        section.append("About Redragon Control", "win.about")
        menu.append_section(None, section)
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)
        self.menu_button = menu_button
        for name, callback in (("save-profile", self._save_profile),
                               ("load-profile", self._load_profile),
                               ("import-profile", self._import_profile),
                               ("export-profile", self._export_profile),
                               ("about", self._about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        content = _box(spacing=0)
        self.root_stack = Gtk.Stack()
        self.root_stack.add_named(content, "control")
        self.toolbar.set_content(self.root_stack)
        self.demo_banner = Adw.Banner(title="Demo mode · Explore the interface without changing a keyboard")
        content.append(self.demo_banner)

        hero_clamp = Adw.Clamp(maximum_size=1040, tightening_threshold=1040)
        hero_clamp.set_margin_start(30)
        hero_clamp.set_margin_end(30)
        hero_clamp.set_margin_top(14)
        hero_clamp.set_margin_bottom(6)
        content.append(hero_clamp)
        hero = _box(Gtk.Orientation.HORIZONTAL, 24)
        hero.add_css_class("hero-card")
        hero.set_margin_top(0)
        hero.set_valign(Gtk.Align.START)
        hero_clamp.set_child(hero)
        hero_copy = _box(spacing=10)
        for setter in (hero_copy.set_margin_top, hero_copy.set_margin_bottom, hero_copy.set_margin_start):
            setter(24)
        hero_copy.set_hexpand(True)
        hero.append(hero_copy)
        eyebrow = _label("REDRAGON CONTROL", "eyebrow")
        eyebrow.add_css_class("accent")
        hero_copy.append(eyebrow)
        hero_copy.append(_label("Make it yours.", "hero-title"))
        hero_copy.append(_label("Lighting, wheel actions, and key bindings.\nDesigned for your GNOME desktop.", "dim-label", wrap=True))
        status_line = _box(Gtk.Orientation.HORIZONTAL, 8)
        self.connection_pill = _label("Finding keyboard…", "status-pill")
        status_line.append(self.connection_pill)
        hero_copy.append(status_line)
        preview_box = _box(spacing=0)
        preview_box.set_hexpand(True)
        preview_box.set_valign(Gtk.Align.CENTER)
        preview_box.set_margin_end(18)
        preview_box.set_margin_top(10)
        preview_box.set_margin_bottom(12)
        self.preview = KeyboardPreview()
        preview_box.append(self.preview)
        self.preview_caption = _label("LIGHTING PREVIEW · ILLUSTRATION", "keyboard-caption",
                                      wrap=True, xalign=.5)
        preview_box.append(self.preview_caption)
        hero.append(preview_box)

        device_clamp = Adw.Clamp(maximum_size=1040, tightening_threshold=1040)
        device_clamp.set_margin_start(30)
        device_clamp.set_margin_end(30)
        device_clamp.set_margin_top(8)
        device_clamp.set_margin_bottom(0)
        content.append(device_clamp)
        device_bar = _box(Gtk.Orientation.HORIZONTAL, 10)
        device_clamp.set_child(device_bar)
        icon = Gtk.Image(icon_name="input-keyboard-symbolic")
        icon.add_css_class("dim-label")
        device_bar.append(icon)
        self.device_dropdown = Gtk.DropDown.new_from_strings(["Scanning devices…"])
        self.device_dropdown.set_hexpand(True)
        self.device_dropdown.set_tooltip_text("Select the keyboard to manage")
        self.device_dropdown.connect("notify::selected", self._device_selected)
        device_bar.append(self.device_dropdown)
        self.refresh_button = _button(icon="view-refresh-symbolic")
        self.refresh_button.set_tooltip_text("Refresh connected devices")
        self.refresh_button.connect("clicked", lambda *_: self._refresh())
        device_bar.append(self.refresh_button)
        self.stack.set_vexpand(True)
        content.append(self.stack)
        self._build_lighting()
        self._build_buttons()
        self._build_recovery()
        if self._in_setup:
            self._build_setup(device_clamp)
            self._run(self.controller.detect_keyboard)
            self._setup_timer = GLib.timeout_add_seconds(3, self._setup_scan)
            self.connect("close-request", self._setup_closed)
        else:
            self._refresh()

    def _build_setup(self, device_clamp):
        setup = _box(spacing=8)
        self.root_stack.add_named(setup, "setup")
        self.root_stack.set_visible_child_name("setup")
        self.switcher.set_visible(False)
        self.menu_button.set_visible(False)
        self.setup_progress = _label("", "eyebrow", xalign=.5)
        self.setup_progress.set_margin_top(20)
        setup.append(self.setup_progress)
        self.setup_pages = Gtk.Stack(vexpand=True)
        setup.append(self.setup_pages)

        detection = _box(spacing=22)
        detection.add_css_class("page-content")
        detection.set_valign(Gtk.Align.CENTER)
        detection.append(Gtk.Image(icon_name="input-keyboard-symbolic", pixel_size=72))
        detection.append(_label("Let’s find your keyboard", "hero-title", xalign=.5))
        detection.append(_label("Connect your Redragon keyboard using USB or its 2.4 GHz receiver.\nWe’ll detect it automatically. If more than one is connected, choose one below.",
                                "dim-label", wrap=True, xalign=.5))
        self.setup_device_status = _label("Looking for a supported keyboard…", wrap=True, xalign=.5)
        detection.append(self.setup_device_status)
        self._setup_device_clamp = device_clamp
        self._setup_device_parent = device_clamp.get_parent()
        self._setup_device_parent.remove(device_clamp)
        detection.append(device_clamp)
        self.setup_import = _button("Import a profile…")
        self.setup_import.set_halign(Gtk.Align.CENTER)
        self.setup_import.connect("clicked", self._import_setup_profile)
        detection.append(self.setup_import)
        detection.append(_label("Restore saved lighting and key bindings, then go straight to Welcome.\nImported preferences can be applied from the main app.",
                                "dim-label", wrap=True, xalign=.5))
        self.setup_pages.add_named(detection, "detect")

        self._setup_shared_pages = []
        for name, title, icon in (("lighting", "Lighting", "weather-clear-night-symbolic"),
                                  ("buttons", "Buttons & wheel", "input-mouse-symbolic")):
            widget = self.stack.get_child_by_name(name)
            self.stack.remove(widget)
            self.setup_pages.add_named(widget, name)
            self._setup_shared_pages.append((widget, name, title, icon))
        lighting_page = self.lighting_page
        self.setup_preview = KeyboardPreview()
        lighting_page.insert_child_after(self.setup_preview, lighting_page.get_first_child())
        self._setup_hidden_widgets = (self.lighting_actions, self.lighting_runtime,
                                      self.remapper_row, self.wheel_actions)
        for widget in self._setup_hidden_widgets:
            widget.set_visible(False)
        self._lighting_subtitle = lighting_page.get_first_child().get_last_child()
        self._lighting_subtitle.set_label("Apply your lighting here, or select Next to keep your current onboard effect.")

        welcome = _box(spacing=22)
        welcome.add_css_class("page-content")
        welcome.set_valign(Gtk.Align.CENTER)
        welcome.append(Gtk.Image(icon_name="input-keyboard-symbolic", pixel_size=72))
        welcome.append(_label("Welcome to Redragon Control", "hero-title", wrap=True, xalign=.5))
        welcome.append(_label("Your keyboard, your way.\nYou can adjust lighting, wheel actions, and key bindings whenever you like.",
                              "dim-label", wrap=True, xalign=.5))
        self.setup_summary = _label("", wrap=True, xalign=.5)
        welcome.append(self.setup_summary)
        self.setup_pages.add_named(welcome, "welcome")

        navigation = _box(Gtk.Orientation.HORIZONTAL, 12)
        for setter in (navigation.set_margin_start, navigation.set_margin_end, navigation.set_margin_bottom):
            setter(30)
        self.setup_back = _button("Back")
        self.setup_back.connect("clicked", self._setup_go_back)
        navigation.append(self.setup_back)
        navigation.append(Gtk.Box(hexpand=True))
        self.setup_apply = _button("Apply")
        self.setup_apply.connect("clicked", self._apply_setup)
        navigation.append(self.setup_apply)
        self.setup_next = _button("Continue", css_class="suggested-action")
        self.setup_next.connect("clicked", self._advance_setup)
        navigation.append(self.setup_next)
        setup.append(navigation)
        self.setup_navigation = navigation
        self._show_setup_step(0)

    def _show_setup_step(self, step):
        if self._busy:
            return
        self._setup_step = step
        names = ("detect", "lighting", "buttons", "welcome")
        titles = ("KEYBOARD", "LIGHTING", "WHEEL & KEYS", "READY")
        self.setup_progress.set_label(f"STEP {step + 1} OF 4 · {titles[step]}")
        self.setup_pages.set_visible_child_name(names[step])
        self.setup_back.set_visible(step > 0)
        self.setup_apply.set_visible(step in (1, 2))
        self.setup_next.set_label(("Continue", "Next", "Next", "Open Redragon Control")[step])
        self._update_setup_navigation()

    def _update_setup_navigation(self):
        if not self._in_setup:
            return
        device = self.state.get("device")
        self.setup_next.set_sensitive(not self._busy and (self._setup_step != 0 or bool(device)))
        self.setup_import.set_sensitive(not self._busy)
        self.setup_apply.set_sensitive(not self._busy)
        if self._setup_step == 1:
            index = self.mode_dropdown.get_selected()
            mode = MODES[index] if index < len(MODES) else "static"
            self.setup_apply.set_sensitive(not self._busy and bool(device) and (
                self.controller.demo or mode in self.state.get("capabilities", {}).get("modes", ())))
        elif self._setup_step == 2:
            self.setup_apply.set_sensitive(not self._busy and bool(device) and (
                self.controller.demo or bool(self.state.get("capabilities", {}).get("remap"))))
        devices = self.state.get("devices", [])
        text = (f"Detected: {device['name']} · {device.get('transport', 'USB')}" if device else
                "Multiple keyboards detected. Choose your keyboard below." if len(devices) > 1 else
                "No keyboard detected yet. Check the connection; we’ll keep looking.")
        self.setup_device_status.set_label(text)
        self.setup_summary.set_label(
            ("Profile imported · Lighting preferences and key bindings saved\n" if self._setup_profile_imported else "") +
            (device['name'] if device else "Select your keyboard in Redragon Control when connected") + "\n" +
            ("App lighting is active" if self.state.get("lighting_daemon", {}).get("running") else "Using onboard lighting") + " · " +
            ("Remapping is active" if self.state.get("daemon", {}).get("running") else "Using default key actions"))

    def _setup_scan(self):
        if not self._in_setup:
            return GLib.SOURCE_REMOVE
        if self._setup_step == 0 and not self._busy and not self._setup_import_pending:
            self._run(self.controller.detect_keyboard)
        return GLib.SOURCE_CONTINUE

    def _setup_closed(self, *_):
        if self._setup_timer:
            GLib.source_remove(self._setup_timer)
            self._setup_timer = None
        return False

    def _setup_go_back(self, *_):
        self._show_setup_step(0 if self._setup_profile_imported and self._setup_step == 3 else self._setup_step - 1)

    def _import_setup_profile(self, *_):
        if self._busy:
            return
        self._setup_import_pending = True
        self._file_dialog(False, self._load_setup_profile, self._setup_import_closed)

    def _setup_import_closed(self):
        self._setup_import_pending = False

    def _load_setup_profile(self, path):
        def imported(_result):
            self._setup_profile_imported = True
            self._show_setup_step(3)
        self._run(lambda: self.controller.import_profile(path), imported)

    def _apply_setup(self, *_):
        if self._busy:
            return
        if self._setup_step == 1:
            self._save_lighting(apply=True)
        elif self._setup_step == 2:
            self._save_wheel(start=True)

    def _advance_setup(self, *_):
        if self._setup_step == 0:
            # Recheck the connection rather than trusting an earlier scan.
            def detect():
                state = self.controller.detect_keyboard()
                if not state['device']:
                    raise ControlError("Connect and select your keyboard before continuing.")
            def detected(_result):
                self._setup_profile_imported = False
                self._show_setup_step(1)
            self._run(detect, detected)
        elif self._setup_step in (1, 2):
            if self._busy:
                return
            self._render_state(self.state)
            self._show_setup_step(self._setup_step + 1)
        else:
            self._run(lambda: None if self.controller.demo else self.setup_store.finish(),
                      lambda *_: self._finish_setup())

    def _finish_setup(self):
        self._in_setup = False
        self._setup_closed()
        recovery = self.stack.get_child_by_name("recovery")
        self.stack.remove(recovery)
        for widget, name, title, icon in self._setup_shared_pages:
            self.setup_pages.remove(widget)
            self.stack.add_titled_with_icon(widget, name, title, icon)
        self.stack.add_titled_with_icon(recovery, "recovery", "Recovery", "document-revert-symbolic")
        self.setup_preview.get_parent().remove(self.setup_preview)
        self._lighting_subtitle.set_label("A little color for your everyday setup.")
        self._setup_device_clamp.get_parent().remove(self._setup_device_clamp)
        self._setup_device_parent.insert_child_after(self._setup_device_clamp,
                                                     self._setup_device_parent.get_first_child().get_next_sibling())
        for widget in self._setup_hidden_widgets:
            widget.set_visible(True)
        self.root_stack.set_visible_child_name("control")
        self.switcher.set_visible(True)
        self.menu_button.set_visible(True)
        self.stack.set_visible_child_name("lighting")
        self._render_state(self.state)

    def _page(self, name, title, subtitle, icon):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_vexpand(True)
        clamp = Adw.Clamp(maximum_size=1040, tightening_threshold=1040)
        scroll.set_child(clamp)
        page = _box(spacing=18)
        page.add_css_class("page-content")
        clamp.set_child(page)
        heading = _box(spacing=5)
        heading.append(_label(title, "section-title"))
        heading.append(_label(subtitle, "dim-label", wrap=True))
        page.append(heading)
        self.stack.add_titled_with_icon(scroll, name, title, icon)
        return page

    @staticmethod
    def _note(text, icon="dialog-information-symbolic", warning=False):
        box = _box(Gtk.Orientation.HORIZONTAL, 12)
        box.add_css_class("note-card")
        if warning:
            box.add_css_class("warning")
        image = Gtk.Image(icon_name=icon)
        image.set_valign(Gtk.Align.START)
        box.append(image)
        label = _label(text, wrap=True)
        label.set_hexpand(True)
        box.append(label)
        return box, label

    def _build_lighting(self):
        page = self._page("lighting", "Lighting", "A little color for your everyday setup.", "weather-clear-night-symbolic")
        self.lighting_page = page
        self.rgb_note, self.rgb_note_label = self._note("Checking lighting support…")
        page.append(self.rgb_note)
        group = Adw.PreferencesGroup(title="Lighting preferences")
        page.append(group)
        mode_row = Adw.ActionRow(title="Effect", subtitle="Choose a lighting style")
        self.effect_row = mode_row
        self.mode_dropdown = Gtk.DropDown.new_from_strings(MODE_LABELS)
        self.mode_dropdown.set_valign(Gtk.Align.CENTER)
        self.mode_dropdown.connect("notify::selected", self._lighting_preview_changed)
        mode_row.add_suffix(self.mode_dropdown)
        mode_row.set_activatable_widget(self.mode_dropdown)
        group.add(mode_row)

        color_row = Adw.ActionRow(title="Color", subtitle="Static color and Smooth breathing; other effects retain onboard colors")
        self.color_entry = Gtk.Entry(text="#E74957", max_length=7, width_chars=8)
        self.color_entry.add_css_class("key-entry")
        self.color_entry.set_valign(Gtk.Align.CENTER)
        self.color_entry.connect("changed", self._lighting_preview_changed)
        color_row.add_suffix(self.color_entry)
        dialog = Gtk.ColorDialog(title="Choose a lighting color", with_alpha=False)
        self.color_button = Gtk.ColorDialogButton(dialog=dialog)
        self.color_button.set_valign(Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse("#E74957")
        self.color_button.set_rgba(rgba)
        self.color_button.connect("notify::rgba", self._color_selected)
        color_row.add_suffix(self.color_button)
        self.native_color_dropdown = Gtk.DropDown.new_from_strings(
            ['Red', 'Green', 'Blue', 'Yellow', 'Magenta', 'Cyan', 'White'])
        self.native_color_dropdown.set_valign(Gtk.Align.CENTER)
        self.native_color_dropdown.connect('notify::selected', self._native_color_selected)
        self.native_color_dropdown.set_visible(False)
        color_row.add_suffix(self.native_color_dropdown)
        group.add(color_row)

        self.brightness_scale = self._scale_row(group, "Brightness", "From subtle to vivid", 0, 100, 1, 70)
        self.speed_scale = self._scale_row(group, "Effect speed", "For animated lighting effects", 0, 100, 1, 50)
        self.speed_scale.connect("value-changed", self._lighting_preview_changed)
        self.brightness_scale.connect("value-changed", self._lighting_preview_changed)
        actions = _box(Gtk.Orientation.HORIZONTAL, 10)
        self.lighting_actions = actions
        self.onboard_button = _button("Use onboard lighting")
        self.onboard_button.set_tooltip_text("Stop lighting control and restore the keyboard’s original lighting")
        self.onboard_button.connect("clicked", lambda *_: self._run(self.controller.stop_lighting, "Lighting control stopped · original onboard lighting restored"))
        actions.append(self.onboard_button)
        spacer = Gtk.Box(hexpand=True)
        actions.append(spacer)
        self.lighting_save = _button("Save preferences")
        self.lighting_save.connect("clicked", self._save_lighting)
        actions.append(self.lighting_save)
        self.lighting_apply = _button("Apply lighting", css_class="suggested-action")
        self.lighting_apply.connect("clicked", lambda *_: self._save_lighting(apply=True))
        actions.append(self.lighting_apply)
        page.append(actions)
        self.lighting_runtime = _label("Lighting control is stopped", "dim-label", wrap=True)
        page.append(self.lighting_runtime)

    @staticmethod
    def _scale_row(group, title, subtitle, minimum, maximum, step, value):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum, maximum, step)
        scale.set_value(value)
        scale.set_digits(0)
        scale.set_draw_value(True)
        scale.set_size_request(230, -1)
        scale.set_valign(Gtk.Align.CENTER)
        row.add_suffix(scale)
        group.add(row)
        return scale

    def _build_buttons(self):
        page = self._page("buttons", "Buttons & wheel", "Give your controls a new job.", "input-mouse-symbolic")
        live = Adw.PreferencesGroup()
        page.append(live)
        self.remapper_row = Adw.ActionRow(title="Live remapper", subtitle="Checking device support…")
        self.remapper_indicator = Gtk.Image(icon_name="media-playback-stop-symbolic")
        self.remapper_row.add_prefix(self.remapper_indicator)
        self.remapper_button = _button("Start remapper", css_class="suggested-action")
        self.remapper_button.set_valign(Gtk.Align.CENTER)
        self.remapper_button.connect("clicked", self._toggle_remapper)
        self.remapper_row.add_suffix(self.remapper_button)
        live.add(self.remapper_row)

        group = Adw.PreferencesGroup(title="Wheel controls", description="These are standard Linux media-key events. Verify which events your keyboard emits before starting the remapper.")
        page.append(group)
        for source, title, subtitle in PRESET_SOURCES:
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            editor = Gtk.ComboBoxText.new_with_entry()
            for target in TARGETS:
                editor.append(target, TARGET_LABELS[target])
            editor.set_active_id("default")
            editor.get_child().add_css_class("key-entry")
            editor.set_valign(Gtk.Align.CENTER)
            editor.set_size_request(240, -1)
            editor.set_tooltip_text("Linux key name, key chord, or disabled")
            self._binding_editors[source] = editor
            row.add_suffix(editor)
            group.add(row)
        buttons = _box(Gtk.Orientation.HORIZONTAL, 10)
        self.wheel_actions = buttons
        buttons.set_halign(Gtk.Align.END)
        save = _button("Save wheel actions", css_class="suggested-action")
        save.connect("clicked", self._save_wheel)
        buttons.append(save)
        page.append(buttons)

        self.custom_group = Adw.PreferencesGroup(title="Other buttons", description="Remap a Linux key event to another key or a chord, such as KEY_LEFTCTRL+KEY_C.")
        add = _button(icon="list-add-symbolic")
        add.set_tooltip_text("Add a key binding")
        add.connect("clicked", self._add_binding)
        self.custom_group.set_header_suffix(add)
        page.append(self.custom_group)
        self.custom_rows = []
        note, _ = self._note("Bindings run on this computer while the remapper is active. They are saved locally and are not written to the keyboard’s firmware.")
        page.append(note)

    def _build_recovery(self):
        page = self._page("recovery", "Recovery", "A clear path back to a familiar setup.", "document-revert-symbolic")
        group = Adw.PreferencesGroup(title="Keyboard recovery")
        page.append(group)
        self.factory_row = Adw.ActionRow(title="Factory defaults", subtitle="Checking hardware reset support…")
        self.factory_row.add_prefix(Gtk.Image(icon_name="input-keyboard-symbolic"))
        self.factory_button = _button("View reset guidance")
        self.factory_button.set_valign(Gtk.Align.CENTER)
        self.factory_button.connect("clicked", self._factory_reset)
        self.factory_row.add_suffix(self.factory_button)
        group.add(self.factory_row)

        local = Adw.PreferencesGroup(title="App recovery", description="App settings and keyboard firmware are separate.")
        page.append(local)
        row = Adw.ActionRow(title="Reset app settings", subtitle="Stop lighting control and remapping; restore local preferences")
        row.add_prefix(Gtk.Image(icon_name="edit-undo-symbolic"))
        reset = _button("Reset app settings…", css_class="destructive-action")
        reset.set_valign(Gtk.Align.CENTER)
        reset.connect("clicked", self._reset_app)
        row.add_suffix(reset)
        local.add(row)
        note, _ = self._note("Export a profile from the menu before making changes you want to keep. Profiles include your lighting preferences and button bindings.")
        page.append(note)

    def _run(self, function, success=None, *, refresh=True):
        if self._busy:
            self._toast("Please wait for the current operation to finish.")
            return
        self._busy = True
        self.activity.set_visible(True)
        self.activity.start()
        self.refresh_button.set_sensitive(False)
        if self._in_setup:
            self.setup_navigation.set_sensitive(False)
            self.setup_import.set_sensitive(False)

        def work():
            try:
                result = function()
                state = self.controller.status() if refresh else None
                GLib.idle_add(finish, result, state, None)
            except Exception as error:
                GLib.idle_add(finish, None, None, error)

        def finish(result, state, error):
            self._busy = False
            self.activity.stop()
            self.activity.set_visible(False)
            self.refresh_button.set_sensitive(True)
            if self._in_setup:
                self.setup_navigation.set_sensitive(True)
            if error:
                self._error(error)
            else:
                if state is not None:
                    self._render_state(state)
                if callable(success):
                    success(result)
                elif success:
                    self._toast(success)
            self._update_setup_navigation()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, name="redragon-ui-operation", daemon=True).start()

    def _refresh(self):
        self._run(self.controller.detect_keyboard if self._in_setup and self._setup_step == 0 else lambda: None)

    def _render_state(self, state):
        if self._in_setup:
            state = dict(state, devices=keyboard_candidates(state.get('devices', [])))
            if state.get('device') not in state['devices']:
                state['device'] = None
        self.state = state
        self._updating = True
        try:
            demo = bool(state.get("demo"))
            self.demo_banner.set_revealed(demo)
            device = state.get("device")
            devices = state.get("devices", [])
            self._device_ids = [item.get("id", item.get("path", "")) for item in devices]
            names = [str(item.get("name", item.get("product", item.get("id", "Keyboard")))) for item in devices]
            if devices and not device:
                self._device_ids.insert(0, None)
                names.insert(0, "Choose a keyboard…")
            self.device_dropdown.set_model(Gtk.StringList.new(names or ["No supported keyboard detected"]))
            self.device_dropdown.set_sensitive(bool(devices) and not demo)
            if device:
                selected_id = device.get("id", device.get("path"))
                if selected_id in self._device_ids:
                    self.device_dropdown.set_selected(self._device_ids.index(selected_id))
            self.connection_pill.remove_css_class("connected")
            self.connection_pill.remove_css_class("demo")
            if demo:
                self.connection_pill.set_label("Demo keyboard")
                self.connection_pill.add_css_class("demo")
            elif device:
                self.connection_pill.set_label("Keyboard detected")
                self.connection_pill.add_css_class("connected")
            else:
                self.connection_pill.set_label("Connect your keyboard")
            capabilities = state.get("capabilities", {})
            rgb_supported = bool(capabilities.get("rgb"))
            self.rgb_note_label.set_label(state.get("rgb_message") or (
                "Lighting settings can be applied to this keyboard." if rgb_supported else
                "Lighting control is not verified for this keyboard. Preferences are saved locally; device support is pending."))
            self.lighting_apply.set_sensitive(rgb_supported and not demo)
            lighting_running = bool(state.get("lighting_daemon", {}).get("running"))
            self.onboard_button.set_sensitive(lighting_running and not demo)
            self.lighting_runtime.set_label(
                "Demo preview · no keyboard is changed" if demo else
                "Built-in effect runs on the keyboard · Original lighting is saved for recovery"
                if lighting_running and state.get('config', {}).get('lighting', {}).get('mode') in NATIVE_EFFECTS
                and capabilities.get('native_effects') else
                "Static lighting is active · Refresh runs in the background" if lighting_running else
                "Lighting control is stopped · The keyboard uses its onboard effect")
            lighting = _lighting(state.get("config", {}))
            mode = lighting.get("mode", "rainbow")
            self.mode_dropdown.set_selected(MODES.index(mode) if mode in MODES else 0)
            color = lighting.get("color", "#E74957")
            if isinstance(color, str):
                self.color_entry.set_text(color)
                rgba = Gdk.RGBA()
                if rgba.parse(color):
                    self.color_button.set_rgba(rgba)
            self.brightness_scale.set_value(lighting.get("brightness", 70))
            self.speed_scale.set_value(lighting.get("speed", 50))
            bindings = _bindings(state.get("config", {}))
            for source, editor in self._binding_editors.items():
                value = bindings.get(source, "default")
                if value in TARGET_LABELS:
                    editor.set_active_id(value)
                else:
                    editor.set_active(-1)
                    editor.get_child().set_text(str(value))
            self._render_custom_bindings(bindings)
            if self._in_setup:
                self._setup_bindings = dict(bindings)
            running = bool(state.get("daemon", {}).get("running"))
            remap_supported = bool(capabilities.get("remap"))
            self.remapper_button.set_label("Stop remapper" if running else "Start remapper")
            self.remapper_button.set_sensitive((running or remap_supported) and not demo)
            self.remapper_button.remove_css_class("suggested-action")
            self.remapper_button.remove_css_class("destructive-action")
            self.remapper_button.add_css_class("destructive-action" if running else "suggested-action")
            self.remapper_indicator.set_from_icon_name("media-playback-start-symbolic" if running else "media-playback-stop-symbolic")
            subtitle = "Active · Saved bindings are being applied" if running else "Stopped · Start to apply your saved bindings"
            if demo:
                subtitle = "Demo mode · Live input is unavailable"
            elif not remap_supported and not running:
                subtitle = state.get("remap_message") or "Connect a supported device with input access to start"
            self.remapper_row.set_subtitle(subtitle)
            for name in ("save-profile", "load-profile", "import-profile", "export-profile"):
                self.lookup_action(name).set_enabled(not demo and not self._in_setup)
            factory = bool(capabilities.get("factory_reset"))
            self.factory_button.set_label("Restore factory defaults…" if factory else "View reset guidance")
            self.factory_row.set_subtitle("Restore the keyboard’s onboard settings" if factory else "Use the keyboard’s documented reset procedure")
        finally:
            self._updating = False
        self._lighting_preview_changed()
        self._update_setup_navigation()

    def _render_custom_bindings(self, bindings):
        for row in self.custom_rows:
            self.custom_group.remove(row)
        self.custom_rows.clear()
        presets = {item[0] for item in PRESET_SOURCES}
        for source, target in sorted(bindings.items()):
            if source in presets:
                continue
            row = Adw.ActionRow(title=str(source), subtitle=str(target))
            delete = _button(icon="user-trash-symbolic")
            delete.set_tooltip_text("Remove this binding")
            delete.set_valign(Gtk.Align.CENTER)
            delete.connect("clicked", lambda _button, key=source: self._remove_binding(key))
            row.add_suffix(delete)
            self.custom_group.add(row)
            self.custom_rows.append(row)
        if not self.custom_rows:
            row = Adw.ActionRow(title="No additional bindings", subtitle="Use + to add a key or button")
            row.set_sensitive(False)
            self.custom_group.add(row)
            self.custom_rows.append(row)

    def _remove_binding(self, source):
        if self._in_setup:
            self._setup_bindings.pop(source, None)
            self._render_custom_bindings(self._setup_bindings)
        else:
            self._run(lambda: self.controller.remove_binding(source), "Binding removed")

    def _device_selected(self, *_):
        if self._updating:
            return
        index = self.device_dropdown.get_selected()
        if index < len(self._device_ids) and self._device_ids[index]:
            self._run(lambda: self.controller.select_device(self._device_ids[index]), "Keyboard selected")

    def _lighting_preview_changed(self, *_):
        if self._updating:
            return
        index = self.mode_dropdown.get_selected()
        mode = MODES[index] if index < len(MODES) else 'static'
        native = mode in NATIVE_EFFECTS
        preset = mode == 'smooth-breathing'
        if preset:
            color = Gdk.RGBA()
            color.parse(self.color_entry.get_text().strip())
            channels = (color.red, color.green, color.blue)
            def distance(candidate):
                values = [int(candidate[i:i + 2], 16) / 255 for i in (1, 3, 5)]
                return sum((a - b) ** 2 for a, b in zip(channels, values))
            selected = min(range(len(NATIVE_COLORS)), key=lambda i: distance(NATIVE_COLORS[i]))
            self._updating = True
            try:
                self.native_color_dropdown.set_selected(selected)
                if self.color_entry.get_text().lower() != NATIVE_COLORS[selected]:
                    self.color_entry.set_text(NATIVE_COLORS[selected])
            finally:
                self._updating = False
        if native:
            self._updating = True
            try:
                for scale in (self.brightness_scale, self.speed_scale):
                    value = round(scale.get_value() / 25) * 25
                    if scale.get_value() != value:
                        scale.set_value(value)
            finally:
                self._updating = False
        detail = ('Runs on the keyboard · seven preset colors and five levels' if preset else
                  'Runs on the keyboard · uses its onboard colors; five brightness/speed levels')
        if mode in REACTIVE_MODES:
            detail += ' · Type to see this effect'
        mode_supported = mode in self.state.get('capabilities', {}).get('modes', ())
        if native and not mode_supported and not self.state.get('demo'):
            detail = 'Use the K686 MAX 2.4 GHz receiver for built-in animations'
        self.effect_row.set_subtitle(detail if native else 'Choose a lighting style')
        self.lighting_apply.set_sensitive(mode_supported and not self.state.get('demo'))
        self.native_color_dropdown.set_visible(preset)
        self.color_button.set_visible(mode == 'static')
        self.preview_caption.set_text(
            EFFECT_DESCRIPTIONS[mode] + "\n" +
            ("Simulated key presses · illustrative colors and timing" if mode in REACTIVE_MODES else
             "Illustrative colors and timing" if native and not preset else "Lighting preview"))
        self.preview.configure(mode,
                               self.color_entry.get_text().strip(),
                               self.brightness_scale.get_value(), self.speed_scale.get_value())
        if self._in_setup:
            self.setup_preview.configure(mode, self.color_entry.get_text().strip(),
                                         self.brightness_scale.get_value(), self.speed_scale.get_value())
            self._update_setup_navigation()
        color_enabled = mode == 'static'
        self.color_entry.set_sensitive(color_enabled)
        self.color_button.set_sensitive(color_enabled)
        self.speed_scale.set_sensitive(native)

    def _native_color_selected(self, *_):
        if not self._updating and self.mode_dropdown.get_selected() == MODES.index('smooth-breathing'):
            index = self.native_color_dropdown.get_selected()
            if index < len(NATIVE_COLORS):
                self._updating = True
                try:
                    self.color_entry.set_text(NATIVE_COLORS[index])
                finally:
                    self._updating = False
                self._lighting_preview_changed()

    def _color_selected(self, *_):
        if self._updating:
            return
        rgba = self.color_button.get_rgba()
        self.color_entry.set_text("#{:02X}{:02X}{:02X}".format(round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255)))

    def _save_lighting(self, *_, apply=False, success=None):
        mode = MODES[self.mode_dropdown.get_selected()]
        color = self.color_entry.get_text().strip()
        brightness = int(self.brightness_scale.get_value())
        speed = int(self.speed_scale.get_value())
        supported = self.state.get("capabilities", {}).get("rgb") and not self.state.get("demo")
        message = "Lighting applied" if apply and supported else "Lighting preferences saved locally"
        if apply and supported and mode in NATIVE_EFFECTS:
            message = MODE_LABELS[MODES.index(mode)] + ' applied · runs on the keyboard'
        if not supported and not self.state.get("demo"):
            message += " · device support pending"
        if self.state.get("demo"):
            message = "Demo lighting preferences saved · no keyboard changed"
        self._run(lambda: self.controller.set_lighting(mode=mode, color=color, brightness=brightness, speed=speed, apply=apply), success or message)

    def _save_wheel(self, *_, success=None, start=False):
        labels_to_targets = {label: target for target, label in TARGET_LABELS.items()}
        values = {source: labels_to_targets.get(editor.get_child().get_text().strip(), editor.get_child().get_text().strip())
                  for source, editor in self._binding_editors.items()}

        bindings = dict(self._setup_bindings if self._in_setup else self.state.get("config", {}).get("bindings", {}))
        def save():
            for source, target in values.items():
                if target and target != "default":
                    bindings[source] = target
                else:
                    bindings.pop(source, None)
            self.controller.set_bindings(bindings)
            if start and any(target != "default" for target in bindings.values()):
                self.controller.start_daemon()

        self._run(save, success or "Wheel actions saved")

    def _toggle_remapper(self, *_):
        running = bool(self.state.get("daemon", {}).get("running"))
        self._run(self.controller.stop_daemon if running else self.controller.start_daemon,
                  "Remapper stopped" if running else "Remapper started")

    def _add_binding(self, *_):
        dialog = Adw.AlertDialog(heading="Add a button binding", body="Use a Linux input key name for the source. The target can be a key, a chord, or disabled.")
        fields = _box(spacing=10)
        source = Gtk.Entry(placeholder_text="Source · for example KEY_F13")
        target = Gtk.Entry(placeholder_text="Target · for example KEY_LEFTCTRL+KEY_C")
        source.add_css_class("key-entry")
        target.add_css_class("key-entry")
        fields.append(source)
        fields.append(target)
        dialog.set_extra_child(fields)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save binding")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def response(_dialog, name):
            if name == "save":
                source_value, target_value = source.get_text().strip(), target.get_text().strip()
                if self._in_setup:
                    try:
                        validate_binding(source_value, target_value)
                    except ControlError as error:
                        self._error(error)
                        return
                    self._setup_bindings[source_value] = target_value
                    self._render_custom_bindings(self._setup_bindings)
                else:
                    self._run(lambda: self.controller.set_binding(source_value, target_value), "Binding saved")

        dialog.connect("response", response)
        dialog.present(self)

    def _reset_app(self, *_):
        self._confirm("Reset app settings?", "This stops lighting control and the live remapper, then restores this app’s local lighting preferences and bindings. Saved named profiles remain available. Keyboard firmware settings are separate.", "Reset app settings", lambda: self._run(self.controller.reset_app, "App settings restored"))

    def _factory_reset(self, *_):
        if self.state.get("capabilities", {}).get("factory_reset"):
            self._confirm("Restore keyboard factory defaults?", "This restores the keyboard’s onboard settings. Any custom onboard lighting or key settings may be lost.", "Restore factory defaults", lambda: self._run(self.controller.factory_reset, "Keyboard factory defaults restored"))
        else:
            guidance = self.state.get("factory_reset_message") or (
                "A software factory reset has not been verified for this keyboard. Use the factory-reset procedure in the manual supplied with your exact model.\n\n"
                "To undo this app’s changes, stop the remapper or use Reset app settings. This app does not write unverified commands to the keyboard’s firmware.")
            dialog = Adw.AlertDialog(heading="Keyboard factory reset", body=guidance)
            actions = _box(spacing=8)
            stop = _button("Stop app lighting and remapping", css_class="suggested-action")
            stop.set_sensitive(not self.state.get("demo"))

            def stopped(_result):
                stop.set_label("App lighting and remapping are stopped")
                stop.set_sensitive(False)

            stop.connect("clicked", lambda *_: self._run(self.controller.stop_all, stopped))
            actions.append(stop)
            manual_url = self.state.get("manual_url")
            if manual_url:
                manual = Gtk.LinkButton.new_with_label(manual_url, "Open the official keyboard manual")
                manual.set_halign(Gtk.Align.CENTER)
                actions.append(manual)
            dialog.set_extra_child(actions)
            dialog.add_response("close", "Got it")
            dialog.set_default_response("close")
            dialog.present(self)

    def _confirm(self, heading, body, label, callback):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", label)
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _dialog, response: callback() if response == "confirm" else None)
        dialog.present(self)

    def _profile_dialog(self, title, button_label, callback):
        dialog = Adw.AlertDialog(heading=title)
        entry = Gtk.Entry(placeholder_text="Profile name")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", button_label)
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("confirm")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _dialog, response: callback(entry.get_text().strip()) if response == "confirm" else None)
        dialog.present(self)

    def _save_profile(self, *_):
        self._profile_dialog("Save a named profile", "Save profile", lambda name: self._run(lambda: self.controller.save_profile(name), "Profile saved"))

    def _load_profile(self, *_):
        def show(profiles):
            if not profiles:
                self._toast("No saved profiles yet. Save one from the menu.")
                return
            dialog = Adw.AlertDialog(heading="Load a named profile", body="This replaces your current local lighting preferences and bindings.")
            selection = Gtk.DropDown.new_from_strings(profiles)
            dialog.set_extra_child(selection)
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("load", "Load profile")
            dialog.set_response_appearance("load", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_close_response("cancel")
            dialog.connect("response", lambda _dialog, response: self._run(lambda: self.controller.load_profile(profiles[selection.get_selected()]), "Profile loaded") if response == "load" else None)
            dialog.present(self)
        self._run(self.controller.list_profiles, show, refresh=False)

    def _file_dialog(self, save, callback, on_closed=None):
        dialog = Gtk.FileDialog(title="Export profile" if save else "Import profile")
        file_filter = Gtk.FileFilter()
        file_filter.set_name("JSON profiles")
        file_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)
        if save:
            dialog.set_initial_name("redragon-profile.json")

        def chosen(file_dialog, result):
            try:
                selected = file_dialog.save_finish(result) if save else file_dialog.open_finish(result)
                path = selected.get_path()
                if path:
                    callback(path)
                else:
                    self._toast("Choose a local file for your profile.")
            except GLib.Error as error:
                if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self._error(error)
            finally:
                if on_closed:
                    on_closed()

        if save:
            dialog.save(self, None, chosen)
        else:
            dialog.open(self, None, chosen)

    def _export_profile(self, *_):
        self._file_dialog(True, lambda path: self._run(lambda: self.controller.export_profile(path), "Profile exported", refresh=False))

    def _import_profile(self, *_):
        self._file_dialog(False, lambda path: self._run(lambda: self.controller.import_profile(path), "Profile imported"))

    def _about(self, *_):
        dialog = Adw.AboutDialog(application_name="Redragon Control", application_icon=APP_ID, developer_name="Redragon Control contributors", version=__version__, comments="Independent keyboard controls for GNOME. Not affiliated with Redragon.")
        dialog.present(self)

    def _toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=str(message), timeout=5))

    def _error(self, error):
        title = "Could not complete the operation"
        if isinstance(error, ControlError):
            title = "Action needs attention"
        dialog = Adw.AlertDialog(heading=title, body=str(error))
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.present(self)


class ControlApplication(Adw.Application):
    def __init__(self, config_path=None, demo=False):
        import hashlib
        from .config import ConfigStore
        app_id = APP_ID
        path = ConfigStore(config_path).path.resolve()
        if path != ConfigStore().path.resolve():
            app_id += ".p" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
        if demo:
            app_id += ".Demo"
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.config_path = config_path
        self.demo = demo
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = ControlWindow(self, Controller(config_path=self.config_path, demo=self.demo))
        self.window.present()


def run(config_path=None, demo=False):
    """Launch the desktop app; the CLI imports this function on demand."""
    return ControlApplication(config_path=config_path, demo=demo).run([])
