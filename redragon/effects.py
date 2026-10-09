"""K686 effect selections from the official KB.ini and English text.xml."""

# These are configuration selection indices, not the separate HW effect IDs.
NATIVE_EFFECTS = {
    'smooth-breathing': (2, 'Smooth breathing'),
    'rainbow': (3, 'Rainbow'),
    'flash-away': (4, 'Flash Away'),
    'raindrops': (5, 'Raindrops'),
    'rainbow-wheel': (6, 'Rainbow Wheel'),
    'ripple-shining': (7, 'Ripple Shining'),
    'stars-twinkle': (8, 'Stars Twinkle'),
    'shadow-disappear': (9, 'Shadow Disappear'),
    'retro-snake': (10, 'Retro Snake'),
    'neon-stream': (11, 'Neon Stream'),
    'reaction': (12, 'Reaction'),
    'sine-wave': (13, 'Sine Wave'),
    'retinue-scanning': (14, 'Retinue Scanning'),
    'rotating-windmill': (15, 'Rotating Windmill'),
    'colorful-waterfall': (16, 'Colorful Waterfall'),
    'blossoming': (17, 'Blossoming'),
    'rotating-storm': (18, 'Rotating Storm'),
}
MODES = ('off', 'static', 'smooth-breathing', *tuple(k for k in NATIVE_EFFECTS if k != 'smooth-breathing'))
MODE_LABELS = tuple({'static': 'Static color', 'off': 'Off'}.get(k) or NATIVE_EFFECTS[k][1] for k in MODES)


def parameter_location(effect_id):
    if 1 <= effect_id <= 6:
        return 4, 7 + (effect_id - 1) * 2
    if 7 <= effect_id <= 13:
        return 5, 5 + (effect_id - 7) * 2
    if 14 <= effect_id <= 18:
        return 6, 5 + (effect_id - 14) * 2
    raise ValueError('Unknown K686 effect selection')
