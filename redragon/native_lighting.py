"""K686 MAX onboard effects, with verified read-back and durable recovery."""
import json
import os
from pathlib import Path
import select
import time

from .config import NATIVE_COLORS, atomic_write
from .errors import ControlError
from .effects import NATIVE_EFFECTS, parameter_location


def backup_path(config_path):
    path = Path(config_path)
    return path.with_name(path.stem + '.native-lighting-backup.json')


def validate_frames(frames):
    if len(frames) != 10:
        raise ControlError('Incomplete native lighting configuration.')
    for sequence, frame in enumerate(frames):
        if (len(frame) != 20 or frame[:4] != bytes((0x13, 0x44, 10, sequence)) or
                frame[19] != sum(frame[:19]) & 255 or frame[4] != (14 if sequence < 9 else 2)):
            raise ControlError('Invalid native lighting configuration.')
    if frames[9][5:7] != b'\x5a\xa5':
        raise ControlError('Unrecognized native lighting configuration layout.')
    return frames


def breathing_frames(original, settings):
    return effect_frames(original, {**settings, 'mode': 'smooth-breathing'})


def effect_frames(original, settings):
    """Preserve all fields except effect ID and its two parameter bytes."""
    validate_frames(original)
    mode = settings['mode']
    if mode not in NATIVE_EFFECTS:
        raise ControlError('Select a built-in K686 lighting effect.')
    color = settings['color'].lower()
    if mode == 'smooth-breathing' and color not in NATIVE_COLORS:
        raise ControlError('Smooth breathing requires one of the seven preset colors.')
    frames = [bytearray(frame) for frame in original]
    effect_id = NATIVE_EFFECTS[mode][0]
    page, offset = parameter_location(effect_id)
    frames[0][15] = effect_id
    frames[page][offset] = round(settings['brightness'] * 4 / 100)
    speed = round(settings['speed'] * 4 / 100)
    # Preserve each built-in effect's onboard color/variant flags. Only the
    # retained Smooth breathing control explicitly selects a preset color.
    flags = NATIVE_COLORS.index(color) if mode == 'smooth-breathing' else original[page][offset + 1] & 15
    frames[page][offset + 1] = speed << 4 | flags
    for frame in frames:
        frame[-1] = sum(frame[:-1]) & 255
    return [bytes(frame) for frame in frames]


class NativeLighting:
    def __init__(self, hid, device_id, config_path):
        self.hid, self.device_id = hid, device_id
        self.config_path = Path(config_path)
        self.path = backup_path(config_path)
        self.last_settings = None

    def read(self):
        from .lighting import wireless_packet
        frames = {}
        deadline, next_request = time.monotonic() + 4, 0
        while len(frames) < 10:
            now = time.monotonic()
            if now >= deadline:
                raise ControlError('Timed out reading onboard lighting settings.')
            if now >= next_request:
                self.hid.send_output(wireless_packet(0x44, 1))
                next_request = time.monotonic() + .5
            wait = min(deadline, next_request) - time.monotonic()
            if not select.select([self.hid.fd], [], [], max(0, wait))[0]:
                continue
            frame = os.read(self.hid.fd, 20)
            if len(frame) == 20 and frame[:3] == bytes((0x13, 0x44, 10)):
                if frame[19] != sum(frame[:19]) & 255 or frame[3] >= 10:
                    raise ControlError('Invalid onboard lighting response.')
                frames[frame[3]] = frame
        return validate_frames([frames[i] for i in range(10)])

    def _send_acknowledged(self, report, save=False):
        for attempt in range(1 if save else 3):
            # Configuration fragments are idempotent; retransmit a missing
            # echo without repeating the EEPROM apply/save request.
            self.hid.send_output(report)
            deadline = time.monotonic() + (2 if save else .75)
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if not select.select([self.hid.fd], [], [], max(0, remaining))[0]:
                    break
                response = os.read(self.hid.fd, 20)
                if response == report:
                    return
                if (save and len(response) == 20 and response[:4] == report[:4] and
                        response[-1] == sum(response[:-1]) & 255):
                    return
        if not save:
            raise ControlError('Onboard lighting write was not acknowledged.')
        # Apply acknowledgments can be lost; the complete read-back below
        # remains mandatory, including when an acknowledgment was received.

    def write(self, frames):
        from .lighting import wireless_packet
        validate_frames(frames)
        for frame in frames:
            report = bytearray(frame)
            report[1] = 4
            report[-1] = sum(report[:-1]) & 255
            self._send_acknowledged(bytes(report))
        self._send_acknowledged(wireless_packet(0x0a, 1, payload=bytes((4, 7))), save=True)
        actual = self.read()
        if [r[4:19] for r in actual] != [r[4:19] for r in frames]:
            raise ControlError('Onboard lighting read-back did not match. Original settings will be restored.')

    def _original(self):
        try:
            saved = json.loads(self.path.read_text())
            if saved['device_id'] != self.device_id:
                from .devices import ConnectionStore
                if saved['device_id'] not in ConnectionStore(self.config_path).aliases(self.device_id):
                    raise ControlError('Native lighting backup belongs to another keyboard; retain it for recovery.')
            return validate_frames([bytes.fromhex(frame) for frame in saved['frames']])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ControlError(f'Cannot read native lighting recovery backup: {exc}') from exc

    def apply(self, settings):
        key = (settings['mode'], settings['color'].lower() if settings['mode'] == 'smooth-breathing' else None,
               round(settings['brightness'] * 4 / 100), round(settings['speed'] * 4 / 100))
        if key == self.last_settings:
            return
        if not self.path.exists():
            original = self.read()
            # Persist the verified original before the first hardware write.
            atomic_write(self.path, {'device_id': self.device_id, 'frames': [r.hex() for r in original]})
        original = self._original()
        try:
            self.write(effect_frames(original, settings))
        except Exception:
            self.restore()
            raise
        self.last_settings = key

    def restore(self):
        if self.path.exists():
            self.write(self._original())
            self.path.unlink()
        self.last_settings = None


