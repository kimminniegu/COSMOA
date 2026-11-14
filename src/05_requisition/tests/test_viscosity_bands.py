"""점도 구간 변환 테스트 — DB·외부 API 에 접속하지 않습니다."""
import importlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
bands = importlib.import_module("src.05_requisition.viscosity_bands")


class ViscosityBandTest(unittest.TestCase):
    def test_values_and_boundaries_go_to_upper_band(self):
        cases = [(0, "very_thin"), (99.9, "very_thin"), (100, "thin"), (999, "thin"), (1000, "medium"), (4500, "medium"),
                 (9999.5, "medium"), (10000, "thick"), (29999, "thick"), (30000, "very_thick"), (1_000_000, "very_thick")]
        for cp, key in cases:
            with self.subTest(cp=cp):
                self.assertEqual(bands.band_for_cp(cp), key)

    def test_invalid_values_rejected(self):
        for value in (-1, None, "1000", True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bands.band_for_cp(value)

    def test_bands_have_no_gaps(self):
        rows = bands.VISCOSITY_BANDS
        self.assertEqual(rows[0]["min_cp"], 0)
        self.assertIsNone(rows[-1]["max_cp"])
        for lower, upper in zip(rows, rows[1:]):
            self.assertEqual(lower["max_cp"], upper["min_cp"])


if __name__ == "__main__":
    unittest.main()
