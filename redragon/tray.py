"""Compatibility for old launchers: no indicator or background process remains."""


def run(config_path=None, open_settings=False):
    from .core import Controller
    Controller(config_path).retire_background()
    if open_settings:
        from .gui import run as run_gui
        return run_gui(config_path=config_path)
    return 0
