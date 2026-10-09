"""Fail-closed first-launch checks for the distributable Flatpak."""

import os
from pathlib import Path

APP_ID = "io.github.redragon.Control"
SETUP_SCRIPT = Path("/app/share/redragon-control/setup-hardware.sh")


def hardware_problem():
    """Check real access without grabbing keys or sending lighting commands."""
    from .devices import discover_devices

    if not os.access("/dev/uinput", os.R_OK | os.W_OK):
        return ("Your computer has not enabled keyboard remapping access. "
                "Save the hardware setup script below, then run it once in your "
                "normal Terminal with sudo. Reconnect your keyboard and select Check again.")
    devices = [d for d in discover_devices()
               if (d["vendor_id"], d["product_id"]) in ((0x258a, 0x010c), (0x3554, 0xfa09))]
    if not devices:
        return ("Connect your Redragon K686 MAX keyboard by USB or plug in its 2.4 GHz receiver, "
                "then select Check again. Bluetooth lighting is not supported.")
    if any(not d["input_accessible"] or not d["hidraw_accessible"] for d in devices):
        return ("Linux is blocking access to your keyboard. Save and run the hardware setup "
                "script with sudo, then unplug and reconnect the keyboard or receiver. "
                "If this continues, sign out and back in. If you changed permissions in "
                "Flatseal, restore Redragon Control's default device permissions.")
    return None


def ensure_ready():
    """Only return True after hardware and login startup have both succeeded."""
    import uuid
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk

    class ReadinessApplication(Adw.Application):
        def __init__(self):
            # Separate from the real settings window and tray bus names.
            super().__init__(application_id=APP_ID + ".Readiness",
                             flags=Gio.ApplicationFlags.NON_UNIQUE)
            self.ready = False
            self.pending = False
            self.subscription = None
            self.timeout = None

        def do_activate(self):
            self.window = Adw.ApplicationWindow(application=self, title="Redragon Control setup",
                                               default_width=570, default_height=450)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                          margin_top=28, margin_bottom=28, margin_start=28, margin_end=28)
            title = Gtk.Label(label="Get your keyboard ready", xalign=0)
            title.add_css_class("title-1")
            box.append(title)
            self.message = Gtk.Label(wrap=True, xalign=0, selectable=True, vexpand=True)
            box.append(self.message)
            self.command = Gtk.Label(wrap=True, xalign=0, selectable=True)
            box.append(self.command)
            save = Gtk.Button(label="Save hardware setup script…")
            save.connect("clicked", self.save_script)
            box.append(save)
            self.retry = Gtk.Button(label="Check again")
            self.retry.add_css_class("suggested-action")
            self.retry.connect("clicked", self.check)
            box.append(self.retry)
            close = Gtk.Button(label="Close")
            close.connect("clicked", lambda *_: self.quit())
            box.append(close)
            self.window.set_content(box)
            self.check()

        def blocked(self, message):
            print("Redragon Control: " + message, file=__import__("sys").stderr)
            self.message.set_text(message)
            self.window.present()
            self.retry.grab_focus()

        def save_script(self, *_):
            dialog = Gtk.FileDialog(title="Save the one-time keyboard setup",
                                    initial_name="redragon-hardware-setup.sh")
            def saved(dialog, result):
                try:
                    target = dialog.save_finish(result)
                    target.replace_contents(SETUP_SCRIPT.read_bytes(), None, False,
                                            Gio.FileCreateFlags.REPLACE_DESTINATION, None)
                    import shlex
                    path = target.get_path()
                    if not path:
                        raise ValueError("Choose a local folder such as Downloads.")
                    self.command.set_text("Run in your normal Terminal:\n"
                                          "sudo bash " + shlex.quote(path))
                except GLib.Error as exc:
                    if not exc.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                        self.blocked("The script could not be saved. Choose a writable local folder such as Downloads and try again.")
                except (OSError, ValueError):
                    self.blocked("The script could not be saved. Choose a writable local folder such as Downloads and try again.")
            dialog.save(self.window, None, saved)

        def check(self, *_):
            if self.pending:
                return
            try:
                problem = hardware_problem()
            except Exception:
                self.blocked("Your keyboard could not be checked. Reconnect it and try again. "
                             "If this continues, close and reopen Redragon Control.")
                return
            if problem:
                self.blocked(problem)
                return
            self.pending = True
            self.retry.set_sensitive(False)
            self.message.set_text("Allow Redragon Control to start after sign-in and keep your "
                                  "keyboard settings active. Accept your desktop's permission prompt.")
            self.window.present()
            try:
                self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                token = "redragon_" + uuid.uuid4().hex
                sender = self.bus.get_unique_name().lstrip(":").replace(".", "_")
                request_path = "/org/freedesktop/portal/desktop/request/" + sender + "/" + token
                self.subscription = self.bus.signal_subscribe(
                    "org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request", "Response",
                    request_path, None, Gio.DBusSignalFlags.NONE, self.response)
                options = {"handle_token": GLib.Variant("s", token),
                           "reason": GLib.Variant("s", "Keep your keyboard lighting and remapping active after sign-in."),
                           "autostart": GLib.Variant("b", True),
                           "commandline": GLib.Variant("as", ["redragon-control", "tray"]),
                           "dbus-activatable": GLib.Variant("b", False)}
                # Subscribe first so an immediate portal response cannot be lost.
                self.bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                   "org.freedesktop.portal.Background", "RequestBackground",
                                   GLib.Variant("(sa{sv})", ("", options)), GLib.VariantType.new("(o)"),
                                   Gio.DBusCallFlags.NONE, 10000, None)
                self.timeout = GLib.timeout_add_seconds(120, self.expired)
            except GLib.Error:
                self.finish_request()
                self.blocked("Automatic startup is unavailable. Install xdg-desktop-portal and "
                             "the portal package for your desktop (xdg-desktop-portal-gnome for GNOME "
                             "or xdg-desktop-portal-kde for KDE), then sign out and back in. "
                             "Your desktop must support background app permissions. Select Check again afterward.")

        def finish_request(self):
            if self.subscription is not None:
                self.bus.signal_unsubscribe(self.subscription)
                self.subscription = None
            if self.timeout is not None:
                GLib.source_remove(self.timeout)
                self.timeout = None
            self.pending = False
            self.retry.set_sensitive(True)

        def response(self, connection, sender, path, interface, signal, parameters):
            code, results = parameters.unpack()
            self.finish_request()
            if code != 0 or not results.get("background") or not results.get("autostart"):
                self.blocked("Redragon Control was not allowed to start automatically. "
                             "Select Check again and allow background activity and automatic startup "
                             "in your desktop's prompt or app permissions settings.")
                return
            # Permissions may have changed while the desktop prompt was open.
            problem = hardware_problem()
            if problem:
                self.blocked(problem)
                return
            self.ready = True
            self.quit()

        def expired(self):
            self.timeout = None
            self.finish_request()
            self.blocked("The desktop did not finish setting up automatic startup. "
                         "Close any pending permission prompt, select Check again, and allow "
                         "background activity. If no prompt appears, install the portal package "
                         "for your desktop and sign out and back in.")
            return GLib.SOURCE_REMOVE

    app = ReadinessApplication()
    try:
        app.run([])
        return app.ready
    finally:
        if app.pending:
            app.finish_request()
        if hasattr(app, "window"):
            app.window.destroy()

