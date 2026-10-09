"""Spatial lighting illustrations, independent of device control.

Coordinates are key centers in keyboard units (15 columns, six rows).
Reactive modes replay a synthetic key press; no global input is captured.
Onboard palettes, direction variants and phase are not exposed by the device.
"""
import colorsys
import math

from .effects import NATIVE_EFFECTS

EFFECT_DESCRIPTIONS = {
    'off': 'All key lighting off',
    'static': 'One steady color across all keys',
    'smooth-breathing': 'All keys fade in and out together',
    'rainbow': 'Rainbow bands travel across the keys',
    'flash-away': 'A bright band sweeps across and fades behind it',
    'raindrops': 'Scattered colored drops light individual keys',
    'rainbow-wheel': 'Rainbow colors rotate around the center',
    'ripple-shining': 'A key press sends a ripple across nearby keys',
    'stars-twinkle': 'Scattered keys slowly brighten and fade',
    'shadow-disappear': 'Pressed keys leave a fading light',
    'retro-snake': 'A colored trail snakes through the rows',
    'neon-stream': 'Colored streams travel along the rows',
    'reaction': 'Pressed keys flash briefly',
    'sine-wave': 'A colored wave oscillates across the rows',
    'retinue-scanning': 'A scanning band moves back and forth',
    'rotating-windmill': 'Light spokes rotate around the center',
    'colorful-waterfall': 'Colored bands cascade down the rows',
    'blossoming': 'Colored rings expand outward from the center',
    'rotating-storm': 'Curved light trails spiral around the center',
}
REACTIVE_MODES = frozenset(('ripple-shining', 'shadow-disappear', 'reaction'))


def _rainbow(hue, level=1):
    return colorsys.hsv_to_rgb(hue % 1, 1, max(0, min(1, level)))


def _hash(index):
    # Stable pseudo-random values keep a key's twinkle/drop continuous in time.
    return (math.sin(index * 127.1 + 311.7) * 43758.5453) % 1


def sample(settings, elapsed, x, y):
    """Return RGB floats for one key, including brightness and effect envelope."""
    mode = settings.get('mode', 'static')
    brightness = max(0, min(100, settings.get('brightness', 70))) / 100
    speed = max(0, min(100, settings.get('speed', 50)))
    if mode in NATIVE_EFFECTS:
        brightness = round(brightness * 4) / 4
        speed = round(speed / 25) * 25
    t = max(0, elapsed) / (8 - 7 * speed / 100)
    col, row = int(x), int(y)
    index = row * 16 + col
    dx, dy = x - 7.5, (y - 2.5) * 1.7
    radius = math.hypot(dx, dy)
    angle = math.atan2(dy, dx) / math.tau
    level, hue = 1, x / 15 - t
    if mode == 'off':
        return (0, 0, 0)
    if mode in ('static', 'smooth-breathing', 'breathing'):
        color = settings.get('color', '#e74957')
        rgb = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        level = (1 + math.cos(t * math.tau)) / 2 if mode != 'static' else 1
        return tuple(c * brightness * level for c in rgb)
    if mode == 'rainbow':
        pass
    elif mode == 'flash-away':
        distance = (t * 20 - x) % 20
        level, hue = max(0, 1 - distance / 4), t * .3
    elif mode == 'raindrops':
        cycle = t * 2 + _hash(index) * 5
        age = cycle % 1
        level = max(0, 1 - age / .24)
        hue = _hash(index + int(cycle) * 97)
    elif mode == 'rainbow-wheel':
        hue = angle - t
    elif mode == 'stars-twinkle':
        level = max(0, math.sin((t * .6 + _hash(index) * 4) * math.tau)) ** 5
        hue = _hash(index)
    elif mode in REACTIVE_MODES:
        cycle = int(t)
        # Move the simulated press between actual key positions each cycle.
        px, py = ((3.5, 2.5), (10.5, 3.5), (6.5, 1.5))[cycle % 3]
        distance = math.hypot(x - px, (y - py) * 1.7)
        age = t % 1
        hue = cycle * .23
        if mode == 'ripple-shining':
            level = max(0, 1 - abs(distance - age * 18) / 1.4) * (1 - age)
        else:
            fade = 1.0 if mode == 'shadow-disappear' else .28
            level = max(0, 1 - age / fade) if distance < .7 else 0
    elif mode == 'retro-snake':
        position = row * 15 + (x if row % 2 == 0 else 15 - x)
        distance = (t * 90 - position) % 90
        level, hue = max(0, 1 - distance / 13), position / 90 - t
    elif mode == 'neon-stream':
        distance = (x - t * 18 + row * 2) % 9
        level, hue = max(0, 1 - distance / 4), row / 6 + t * .3
    elif mode == 'sine-wave':
        center = 2.5 + 2.2 * math.sin(x / 15 * math.tau - t * math.tau)
        level = max(0, 1 - abs(y - center) / 1.2)
    elif mode == 'retinue-scanning':
        center = (1 - math.cos(t * math.tau)) * 7.5
        level, hue = max(0, 1 - abs(x - center) / 2.5), t * .3
    elif mode == 'rotating-windmill':
        blade = ((angle - t) * 4) % 1
        level, hue = max(0, 1 - blade / .45), angle - t
    elif mode == 'colorful-waterfall':
        hue = y / 6 - t
        level = .25 + .75 * max(0, math.cos((y / 6 - t) * math.tau))
    elif mode == 'blossoming':
        distance = (radius - t * 12) % 12
        level, hue = max(0, 1 - distance / 3), radius / 12 - t
    elif mode == 'rotating-storm':
        spiral = ((angle - radius / 12 - t) * 3) % 1
        level, hue = max(0, 1 - spiral / .55), angle - radius / 12 - t
    else:
        raise ValueError(f'Unsupported preview mode: {mode}')
    return tuple(channel * brightness for channel in _rainbow(hue, level))
