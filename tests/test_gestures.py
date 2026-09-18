import unittest

from keypilot.gestures import GestureRecognizer


class GestureRecognizerTests(unittest.TestCase):
    def make_recognizer(self) -> GestureRecognizer:
        return GestureRecognizer(double_tap_seconds=0.32, hold_seconds=0.55)

    def test_single_tap_is_delayed_until_double_tap_window_expires(self) -> None:
        recognizer = self.make_recognizer()
        recognizer.key_down(1.0)
        self.assertIsNone(recognizer.key_up(1.05))
        self.assertIsNone(recognizer.poll(1.30))
        self.assertEqual(recognizer.poll(1.38), "tap")

    def test_double_tap(self) -> None:
        recognizer = self.make_recognizer()
        recognizer.key_down(1.0)
        self.assertIsNone(recognizer.key_up(1.04))
        recognizer.key_down(1.20)
        self.assertEqual(recognizer.key_up(1.24), "double_tap")
        self.assertIsNone(recognizer.poll(2.0))

    def test_hold(self) -> None:
        recognizer = self.make_recognizer()
        recognizer.key_down(1.0)
        self.assertEqual(recognizer.key_up(1.60), "hold")

    def test_key_repeat_does_not_reset_hold_timer(self) -> None:
        recognizer = self.make_recognizer()
        recognizer.key_down(1.0)
        recognizer.key_down(1.3)
        self.assertEqual(recognizer.key_up(1.56), "hold")

    def test_pending_single_tap_does_not_fire_while_second_press_is_down(self) -> None:
        recognizer = self.make_recognizer()
        recognizer.key_down(1.0)
        recognizer.key_up(1.04)
        recognizer.key_down(1.30)
        self.assertIsNone(recognizer.poll(1.40))

    def test_immediate_mode_fires_each_short_press_on_key_up(self) -> None:
        recognizer = GestureRecognizer(
            double_tap_seconds=0.45,
            hold_seconds=0.60,
            immediate_tap=True,
        )
        recognizer.key_down(1.0)
        self.assertEqual(recognizer.key_up(1.05), "tap")
        recognizer.key_down(1.15)
        self.assertEqual(recognizer.key_up(1.20), "tap")
        self.assertIsNone(recognizer.poll(2.0))


if __name__ == "__main__":
    unittest.main()
