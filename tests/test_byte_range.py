import unittest

from core.byte_range import select_range, UNSATISFIABLE


class ByteRangeTests(unittest.TestCase):
    def test_normal_and_open_ranges(self):
        for header, expected in [('bytes=0-0', (0, 0)), ('bytes=2-5', (2, 5)),
                                 ('bytes=5-', (5, 9)), ('bytes=0-99', (0, 9)),
                                 ('BYTES=0002-0005', (2, 5)), ('bytes=0-9', (0, 9))]:
            with self.subTest(header=header):
                self.assertEqual(select_range(header, 10), expected)

    def test_suffixes_and_empty_files(self):
        self.assertEqual(select_range('bytes=-3', 10), (7, 9))
        self.assertEqual(select_range('bytes=-99', 10), (0, 9))
        self.assertIs(select_range('bytes=-0', 10), UNSATISFIABLE)
        self.assertIs(select_range('bytes=0-', 0), UNSATISFIABLE)
        self.assertIs(select_range('bytes=-3', 0), UNSATISFIABLE)
        self.assertIsNone(select_range(None, 0))

    def test_invalid_and_unsatisfiable(self):
        for header in ('bytes=-', 'bytes=5-3', 'bytes=1-2,4-5', 'items=0-1',
                       'bytes=abc-1', 'bytes=1 - 2', 'bytes=1-2garbage'):
            with self.subTest(header=header):
                self.assertIsNone(select_range(header, 10))
        for header in ('bytes=10-', 'bytes=100-200', 'bytes=10-10'):
            with self.subTest(header=header):
                self.assertIs(select_range(header, 10), UNSATISFIABLE)

    def test_very_large_decimal_positions(self):
        huge = '9' * 5000
        self.assertIs(select_range('bytes=' + huge + '-', 10), UNSATISFIABLE)
        self.assertEqual(select_range('bytes=-' + huge, 10), (0, 9))
        self.assertEqual(select_range('bytes=3-' + huge, 10), (3, 9))
        self.assertEqual(select_range('bytes=' + '0' * 5000 + '2-', 10), (2, 9))
