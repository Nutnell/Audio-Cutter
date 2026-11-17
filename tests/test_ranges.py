import unittest
from app import timestamp, validate, failure_message


class RangeTests(unittest.TestCase):
    def test_requested_ranges(self):
        self.assertEqual(validate('https://youtu.be/example', [('56:22', '59:33'),
                         ('1:33:26', '1:43:26')]), [(3382, 3573), (5606, 6206)])

    def test_invalid_ranges(self):
        for rows in [[], [('59:33', '56:22')], [('1:60', '3:00')], [('', '3:00')]]:
            with self.assertRaises(ValueError):
                validate('https://youtube.com/watch?v=example', rows)

    def test_reject_unrelated_host(self):
        with self.assertRaises(ValueError):
            validate('https://youtube.com.example.org/video', [('0', '10')])

    def test_seconds(self):
        self.assertEqual(timestamp('90'), 90)

    def test_youtube_block_message(self):
        for error in ['HTTP Error 429: Too Many Requests', "Sign in to confirm you’re not a bot"]:
            self.assertIn('YouTube blocked', failure_message(error))
        self.assertIn('See the log', failure_message('Network unavailable'))


if __name__ == '__main__':
    unittest.main()
