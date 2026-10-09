"""GTK3 AppIndicator host. Settings stay in a separate GTK4 process."""

import hashlib
import logging
from pathlib import Path
import signal
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except ValueError:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import Gio, GLib, Gtk

from .background import BackgroundStore, BackgroundSupervisor
from .core import Controller
from .setup import SetupStore


class TrayApplication(Gtk.Application):
    def __init__(self, config_path=None):
        self.controller = Controller(config_path)
        digest = hashlib.sha256(str(self.controller.store.path).encode()).hexdigest()[:12]
        super().__init__(application_id="io.github.redragon.Control.Tray.p" + digest,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.supervisor = BackgroundSupervisor(self.controller)
        self.preferences = BackgroundStore(self.controller.store.path)
        self.indicator = None
        self.busy = False
        self.closing = False
        self.updating = False
        self.settings_process = None
        self.last_error = None

    def do_activate(self):
        # A second autostart/manual invocation activates this instance silently.
        if self.indicator is not None:
            if not SetupStore(self.controller.store.path).completed():
                self.open_settings()
            return
        self.hold()
        icon = Path(__file__).resolve().parent.parent / "data/io.github.redragon.Control.svg"
        self.indicator = AppIndicator.Indicator.new(
            "redragon-control", str(icon), AppIndicator.IndicatorCategory.HARDWARE)
        self.indicator.set_title("Redragon Control")
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        self.status_item = Gtk.MenuItem(label="Starting keyboard services…")
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)
        settings = Gtk.MenuItem(label="Open settings")
        settings.connect("activate", self.open_settings)
        menu.append(settings)
        menu.append(Gtk.SeparatorMenuItem())
        self.toggles = {}
        for kind, label in (("remap", "Keep button remapping active"), ("rgb", "Keep keyboard lighting active")):
            item = Gtk.CheckMenuItem(label=label)
            item.connect("toggled", self.toggle, kind)
            menu.append(item)
            self.toggles[kind] = item
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit and stop keyboard services")
        quit_item.connect("activate", self.request_quit)
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)
        for signum in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self.request_quit)
        self.timer = GLib.timeout_add_seconds(3, self.refresh)
        self.refresh()
        if not SetupStore(self.controller.store.path).completed():
            self.open_settings()

    def open_settings(self, *_):
        # GTK4's unique application instance raises an existing settings window.
        self.settings_process = subprocess.Popen(
            [sys.executable, "-m", "redragon", "--config", str(self.controller.store.path), "gui"],
            start_new_session=True)

    def toggle(self, item, kind):
        if self.updating or self.closing:
            return
        try:
            self.preferences.set(kind, item.get_active())
            self.supervisor.retry_after[kind] = 0
            self.refresh()
        except Exception as exc:
            self.status_item.set_label(str(exc)[:100])

    def refresh(self):
        if self.busy or self.closing:
            return GLib.SOURCE_CONTINUE
        self.busy = True
        def work():
            try:
                state = self.supervisor.tick()
                desired = self.preferences.read()
                GLib.idle_add(self.render, state, desired, None)
            except Exception as exc:
                GLib.idle_add(self.render, None, None, exc)
        threading.Thread(target=work, name="redragon-tray-refresh", daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def render(self, state, desired, error):
        self.busy = False
        if self.closing:
            self.finish_quit()
            return GLib.SOURCE_REMOVE
        if error:
            message = str(error)
        elif state["device"] is None:
            message = "Waiting for selected keyboard"
        else:
            remap = "active" if state["daemon"]["running"] else "waiting" if desired["remap"] else "paused"
            rgb = "active" if state["lighting_daemon"]["running"] else "waiting" if desired["rgb"] else "onboard"
            message = f"Remapping: {remap} · Lighting: {rgb}"
            if self.supervisor.errors:
                message = "Needs attention: " + next(iter(self.supervisor.errors.values()))
        if (error or self.supervisor.errors) and message != self.last_error:
            logging.warning("%s", message)
        self.last_error = message
        self.status_item.set_label(message[:130])
        if desired is not None:
            self.updating = True
            for kind, enabled in desired.items():
                self.toggles[kind].set_active(enabled)
            self.updating = False
        return GLib.SOURCE_REMOVE

    def request_quit(self, *_):
        if self.closing:
            return GLib.SOURCE_REMOVE
        self.closing = True
        # Wait for an in-flight start before stopping, so it cannot escape quit.
        if not self.busy:
            self.finish_quit()
        return GLib.SOURCE_REMOVE

    def finish_quit(self):
        def stop():
            try:
                # Preserve preferences for next login, but release hardware now.
                from . import runtime
                for kind in ("remap", "rgb"):
                    runtime.stop_daemon(self.controller.store.path, kind)
            finally:
                GLib.idle_add(self.quit)
        threading.Thread(target=stop, name="redragon-tray-stop", daemon=True).start()


def run(config_path=None):
    return TrayApplication(config_path).run([])
