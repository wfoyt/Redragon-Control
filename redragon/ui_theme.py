"""Apply Omarchy palettes to GTK, watching theme replacement without polling."""

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk

from .appearance import AppearanceStore, load_palette, omarchy_css, palette_is_dark, palette_paths


class ThemeManager:
    def __init__(self, window, controller):
        self.window, self.controller = window, controller
        self.display = window.get_display()
        self.style = Adw.StyleManager.get_for_display(self.display)
        self.provider = Gtk.CssProvider()
        self.monitors = []
        self.pending = None
        self.signature = None
        self.closed = False
        self.high_contrast_handler = self.style.connect('notify::high-contrast', self._changed)
        self.reload()

    def _watch(self):
        for monitor in self.monitors:
            monitor.cancel()
        self.monitors.clear()
        targets = [AppearanceStore(self.controller.store.path).path, *palette_paths()]
        directories = set()
        for target in targets:
            for directory in (target.parent, target.parent.parent):
                while not directory.is_dir() and directory != directory.parent:
                    directory = directory.parent
                directories.add(directory)
        for directory in directories:
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
                monitor.connect('changed', self._changed)
                self.monitors.append(monitor)
            except GLib.Error:
                pass

    def _changed(self, *_):
        if not self.closed and self.pending is None:
            self.pending = GLib.timeout_add(150, self.reload)

    def reload(self):
        self.pending = None
        if self.closed:
            return GLib.SOURCE_REMOVE
        choice = self.controller.appearance()['resolved_theme']
        palette = load_palette()
        custom = choice == 'omarchy' and not self.style.get_high_contrast()
        css = omarchy_css(palette, variables=Gtk.get_minor_version() >= 16) if custom else ''
        scheme = (Adw.ColorScheme.FORCE_DARK if palette_is_dark(palette) else Adw.ColorScheme.FORCE_LIGHT) if custom else Adw.ColorScheme.DEFAULT
        signature = css, scheme
        if self.signature != signature:
            Gtk.StyleContext.remove_provider_for_display(self.display, self.provider)
            self.style.set_color_scheme(scheme)
            if css:
                self.provider.load_from_string(css)
                Gtk.StyleContext.add_provider_for_display(self.display, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            self.signature = signature
            self.window.queue_draw()
        self._watch()
        return GLib.SOURCE_REMOVE

    def close(self, *_):
        if not self.closed:
            self.closed = True
            if self.pending is not None:
                GLib.source_remove(self.pending)
                self.pending = None
            for monitor in self.monitors:
                monitor.cancel()
            self.monitors.clear()
            self.style.disconnect(self.high_contrast_handler)
            Gtk.StyleContext.remove_provider_for_display(self.display, self.provider)
        return False
