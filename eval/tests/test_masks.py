import unittest

from eval.easyinput_eval.masks import (
    MaskConversionError,
    masks_as_firmware_order,
    pattern_to_masks,
    track_to_mask,
)
from eval.tests.helpers import passing_pattern


class MaskConversionTests(unittest.TestCase):
    def test_step_one_is_bit_zero_and_step_sixteen_is_bit_fifteen(self):
        track = [0] * 16
        track[0] = 1
        track[15] = 1
        self.assertEqual(track_to_mask(track), 0x8001)

    def test_house_kick_mask_is_0x1111(self):
        masks = pattern_to_masks(passing_pattern("G-HOUSE"))
        self.assertEqual(masks["kick"], 0x1111)

    def test_firmware_order_has_exactly_six_masks(self):
        masks = masks_as_firmware_order(passing_pattern("G-HOUSE"))
        self.assertEqual(len(masks), 6)
        self.assertTrue(all(0 <= value <= 0xFFFF for value in masks))

    def test_invalid_step_is_rejected(self):
        with self.assertRaises(MaskConversionError):
            track_to_mask([0] * 15 + [2])

    def test_boolean_step_is_rejected(self):
        with self.assertRaises(MaskConversionError):
            track_to_mask([True] + [0] * 15)


if __name__ == "__main__":
    unittest.main()
