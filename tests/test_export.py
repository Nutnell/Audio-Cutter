"""Exercise the reliable export path with real local audio; no YouTube requests."""
import json
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import App


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Requires FFmpeg')
class ExportTests(unittest.TestCase):
    def test_download_once_and_copy_two_clips(self):
        app = App.__new__(App)
        app.events = queue.Queue()
        app.cancelled = threading.Event()
        app.process = None
        real_popen = subprocess.Popen
        downloads = []

        def local_download(command, **kwargs):
            if '-m' in command and 'yt_dlp' in command:
                downloads.append(command)
                target = command[command.index('-o') + 1].replace('%(ext)s', 'webm')
                command = [shutil.which('ffmpeg'), '-hide_banner', '-nostdin', '-y',
                           '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6',
                           '-c:a', 'libopus', target]
            return real_popen(command, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            with patch('app.subprocess.Popen', side_effect=local_download):
                app.work('https://youtu.be/example', [(1, 3), (3, 5)], Path(folder))
            clips = list(Path(folder).glob('*.webm'))
            messages = list(app.events.queue)
            self.assertTrue(any(k == 'status' and v.startswith('Finished!') for k, v in messages), messages)
            self.assertEqual(len(downloads), 1)
            self.assertNotIn('--download-sections', downloads[0])
            self.assertEqual(len(clips), 2)
            for clip in clips:
                info = json.loads(subprocess.check_output([
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_name',
                    '-of', 'json', str(clip)]))
                self.assertEqual(info['streams'][0]['codec_name'], 'opus')
                self.assertAlmostEqual(float(info['format']['duration']), 2, delta=0.15)
