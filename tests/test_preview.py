import unittest

from redragon.effects import MODES, NATIVE_EFFECTS
from redragon.preview import EFFECT_DESCRIPTIONS, REACTIVE_MODES, sample


class PreviewTests(unittest.TestCase):
    def settings(self, mode, **values):
        return dict(mode=mode, color='#00ffff', brightness=75, speed=50, **values)

    def test_every_mode_has_description_and_bounded_colors(self):
        for mode in MODES:
            self.assertIn(mode, EFFECT_DESCRIPTIONS)
            for t in (0, .4, 1.5, 9, 120):
                for x, y in ((.5, .5), (3.5, 2.5), (10.5, 3.5), (15.5, 4.5)):
                    with self.subTest(mode=mode, t=t, x=x, y=y):
                        self.assertTrue(all(0 <= c <= .75 for c in sample(self.settings(mode), t, x, y)))

    def test_static_breathing_and_off_are_uniform(self):
        for mode in ('off', 'static', 'smooth-breathing'):
            settings = self.settings(mode)
            self.assertEqual(sample(settings, 1, .5, .5), sample(settings, 1, 14.5, 4.5))
        self.assertEqual(sample(self.settings('off'), 0, 0, 0), (0, 0, 0))
        self.assertEqual(sample(self.settings('static'), 0, 0, 0), (0, .75, .75))
        self.assertEqual(sample(self.settings('smooth-breathing'), 2.25, 0, 0), (0, 0, 0))

    def test_spatial_modes_are_distinct_and_animate(self):
        signatures = set()
        for mode in NATIVE_EFFECTS:
            if mode == 'smooth-breathing':
                continue
            settings = self.settings(mode)
            frames = [tuple(sample(settings, t, x + .5, y + .5)
                            for y in range(5) for x in range(16)) for t in (.2, 1.1, 2.3)]
            with self.subTest(mode=mode):
                self.assertGreater(len(set(frames[0])), 1)
                self.assertNotEqual(frames[0], frames[1])
                self.assertNotIn(tuple(frames), signatures)
            signatures.add(tuple(frames))

    def test_reactive_key_and_ripple_have_local_origin(self):
        for mode in REACTIVE_MODES:
            settings = self.settings(mode)
            self.assertGreater(sum(sample(settings, 0, 3.5, 2.5)), 0)
            self.assertEqual(sample(settings, 0, 10.5, 3.5), (0, 0, 0))
        settings = self.settings('reaction')
        self.assertEqual(sample(settings, 2, 3.5, 2.5), (0, 0, 0))

    def test_zero_brightness_and_onboard_palette(self):
        for mode in MODES:
            settings = self.settings(mode)
            settings['brightness'] = 0
            self.assertEqual(sample(settings, .2, 3.5, 2.5), (0, 0, 0))
        for mode in NATIVE_EFFECTS.keys() - {'smooth-breathing'}:
            settings = self.settings(mode)
            changed = dict(settings, color='#ff0000')
            self.assertEqual(sample(settings, .2, 3.5, 2.5), sample(changed, .2, 3.5, 2.5))


if __name__ == '__main__':
    unittest.main()
