"""K686 MAX saved lighting, with verified read-back and explicit recovery."""
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
    if mode not in (*NATIVE_EFFECTS, 'static', 'off'):
        raise ControlError('Select a built-in K686 lighting effect.')
    color = settings['color'].lower()
    if mode in ('static', 'smooth-breathing') and color not in NATIVE_COLORS:
        raise ControlError('Saved lighting requires one of the seven preset colors.')
    frames = [bytearray(frame) for frame in original]
    # Selection 1 is the onboard static effect. Zero brightness implements Off
    # using the same known lighting fields, without a new command or palette.
    effect_id = 1 if mode in ('static', 'off') else NATIVE_EFFECTS[mode][0]
    page, offset = parameter_location(effect_id)
    frames[0][15] = effect_id
    frames[page][offset] = 0 if mode == 'off' else round(settings['brightness'] * 4 / 100)
    speed = (original[page][offset + 1] >> 4 if mode in ('static', 'off')
             else round(settings['speed'] * 4 / 100))
    # Preserve animation color/variant flags. Static and Smooth breathing
    # explicitly select one of the onboard preset slots.
    flags = NATIVE_COLORS.index(color) if mode in ('static', 'smooth-breathing') else original[page][offset + 1] & 15
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
            raise ControlError('Onboard lighting read-back did not match. Previous settings will be restored.')

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
        mode = settings['mode']
        key = (mode, settings['color'].lower() if mode in ('static', 'smooth-breathing') else None,
               0 if mode == 'off' else round(settings['brightness'] * 4 / 100),
               round(settings['speed'] * 4 / 100) if mode in NATIVE_EFFECTS else None)
        if key == self.last_settings:
            return
        self.recover()
        current = self.read()
        desired = effect_frames(current, settings)
        if not self.path.exists():
            # Persist the verified original before the first hardware write.
            atomic_write(self.path, {'device_id': self.device_id, 'frames': [r.hex() for r in current],
                                     'committed': False})
        self._original()  # Verify backup ownership before any hardware write.
        saved = json.loads(self.path.read_text())
        saved['previous_committed'] = saved.get('committed', False)
        saved['rollback_frames'] = [r.hex() for r in current]
        saved['committed'] = False
        atomic_write(self.path, saved)
        try:
            if desired != current:
                self.write(desired)
            saved.update(committed=True, lighting=dict(settings))
            saved.pop('rollback_frames', None)
            saved.pop('previous_committed', None)
            atomic_write(self.path, saved)
        except Exception:
            self.recover()
            raise
        self.last_settings = key

    def recover(self):
        """Recover an interrupted transaction, never undo a completed save."""
        if self.path.exists():
            original = self._original()
            saved = json.loads(self.path.read_text())
            if not saved.get('committed', False):
                try:
                    rollback = validate_frames([bytes.fromhex(frame) for frame in saved['rollback_frames']]) if 'rollback_frames' in saved else original
                except (ValueError, TypeError) as exc:
                    raise ControlError(f'Cannot read interrupted lighting transaction: {exc}') from exc
                self.write(rollback)
                if saved.get('previous_committed', False):
                    saved['committed'] = True
                    saved.pop('rollback_frames', None)
                    saved.pop('previous_committed', None)
                    atomic_write(self.path, saved)
                else:
                    self.path.unlink()
                self.last_settings = None

    def restore(self):
        if self.path.exists():
            original = self._original()
            saved = json.loads(self.path.read_text())
            saved.update(committed=False, previous_committed=False,
                         rollback_frames=[r.hex() for r in original])
            atomic_write(self.path, saved)
            self.write(original)
            self.path.unlink()
        self.last_settings = None


