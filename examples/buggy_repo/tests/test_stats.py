import unittest
from stats import mean


class MeanTests(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(mean([2, 4]), 3.0)

    def test_empty(self):
        self.assertEqual(mean([]), 0.0)

    def test_negative(self):
        self.assertEqual(mean([-4, -2]), -3.0)

    def test_single(self):
        self.assertEqual(mean([7]), 7.0)
