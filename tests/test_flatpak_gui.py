"""Run with REDRAGON_FLATPAK_GUI_TESTS=1 on an isolated GTK4 display."""

import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("REDRAGON_FLATPAK_GUI_TESTS") == "1", "requires an isolated GTK display")
class FlatpakReadinessGuiTests(unittest.TestCase):
    def run_gate(self, hardware=None, response=(0, {"background": True, "autostart": True}), portal_error=False):
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, GLib, Gtk
        from redragon.flatpak_support import ensure_ready

        observed = {}
        class Bus:
            def get_unique_name(self):
                return ":1.42"

            def signal_subscribe(self, *args):
                self.callback = args[-1]
                observed["request_path"] = args[3]
                return 1

            def signal_unsubscribe(self, number):
                observed["unsubscribed"] = True

            def call_sync(self, *args):
                observed["options"] = args[4].unpack()[1]
                if portal_error:
                    raise GLib.Error("Background portal unavailable")
                def respond():
                    values = {key: GLib.Variant("b", value) for key, value in response[1].items()}
                    self.callback(None, None, None, None, None, GLib.Variant("(ua{sv})", (response[0], values)))
                    return GLib.SOURCE_REMOVE
                GLib.idle_add(respond)
                return GLib.Variant("(o)", (observed["request_path"],))

        def inspect_and_close():
            app = next(window.get_application() for window in Gtk.Window.list_toplevels()
                       if window.get_visible() and window.get_title() == "Redragon Control setup")
            observed["ready"] = app.ready
            observed["message"] = app.message.get_text()
            observed["window_visible"] = app.window.get_visible()
            app.quit()
            return GLib.SOURCE_REMOVE

        # On failure there is deliberately no automatic continuation. Close
        # the visible gate after inspecting it, as a user would do.
        failure = hardware is not None or portal_error or response[0] != 0 or not all(response[1].get(k) for k in ("background", "autostart"))
        if failure:
            GLib.timeout_add(150, inspect_and_close)
        with patch("redragon.flatpak_support.hardware_problem", return_value=hardware), \
             patch.object(Gio, "bus_get_sync", return_value=Bus()):
            result = ensure_ready()
        return result, observed

    def test_hardware_failure_stays_at_setup_window(self):
        ready, observed = self.run_gate(hardware="Save the setup script and run it with sudo.")
        self.assertFalse(ready)
        self.assertFalse(observed["ready"])
        self.assertTrue(observed["window_visible"])
        self.assertIn("sudo", observed["message"])
        self.assertNotIn("options", observed)

    def test_denied_background_permission_blocks_main_app(self):
        ready, observed = self.run_gate(response=(1, {}))
        self.assertFalse(ready)
        self.assertIn("not allowed", observed["message"])
        self.assertTrue(observed["unsubscribed"])

    def test_autostart_denial_is_not_treated_as_success(self):
        ready, observed = self.run_gate(response=(0, {"background": True, "autostart": False}))
        self.assertFalse(ready)
        self.assertIn("Check again", observed["message"])

    def test_missing_portal_explains_what_to_install(self):
        ready, observed = self.run_gate(portal_error=True)
        self.assertFalse(ready)
        self.assertIn("xdg-desktop-portal-gnome", observed["message"])
        self.assertIn("xdg-desktop-portal-kde", observed["message"])

    def test_only_confirmed_background_and_autostart_allow_launch(self):
        ready, observed = self.run_gate()
        self.assertTrue(ready)
        self.assertEqual(observed["options"]["commandline"], ["redragon-control", "tray"])
        self.assertTrue(observed["options"]["autostart"])
        self.assertTrue(observed["unsubscribed"])


if __name__ == "__main__":
    unittest.main()
