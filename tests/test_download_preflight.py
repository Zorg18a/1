"""Preflight observes temporary paths without creating or changing anything."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from storage import download_preflight


class DownloadPreflightTests(unittest.TestCase):
    def test_directory_states_and_no_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / 'not-created'
            self.assertEqual(download_preflight.folder_status(str(missing))['state'], 'missing')
            self.assertFalse(missing.exists())
            file = root / 'file'; file.write_bytes(b'data')
            self.assertEqual(download_preflight.folder_status(str(file))['state'], 'not_directory')
            self.assertEqual(download_preflight.folder_status('relative')['state'], 'relative')
            self.assertEqual(download_preflight.folder_status('')['state'], 'invalid')
            self.assertEqual(download_preflight.folder_status('bad\0path')['state'], 'invalid')
            self.assertEqual(download_preflight.folder_status(None)['state'], 'invalid')
            result = download_preflight.folder_status(str(root))
            self.assertEqual(result['state'], 'directory')
            self.assertGreaterEqual(int(result['free_bytes']), 0)
            with patch('storage.download_preflight.shutil.disk_usage', side_effect=PermissionError()):
                self.assertEqual(download_preflight.folder_status(str(root)), {'state': 'directory', 'free_bytes': None})
            with patch('pathlib.Path.stat', side_effect=PermissionError()):
                self.assertEqual(download_preflight.folder_status(str(root))['state'], 'unknown')
            self.assertEqual(file.read_bytes(), b'data')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['file'])

    def test_unc_or_device_path_skipped_on_windows(self):
        import os
        if os.name != 'nt':
            self.skipTest('Windows-specific path')
        with patch('pathlib.Path.stat', side_effect=AssertionError('must not access network')):
            for value in (r'\\\\server\\share', '//server/share', r'\\\\?\\C:\\unsafe'):
                self.assertEqual(download_preflight.folder_status(value)['state'], 'network_skipped')

    def test_tools_respect_explicit_directory_and_do_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('storage.download_preflight.shutil.which', return_value='/different/tool') as which:
                result = download_preflight.tool_status(root / 'absent')
                self.assertEqual(result, {'source': 'path', 'ffmpeg': 'found', 'ffprobe': 'found'})
                self.assertEqual(which.call_count, 2)
                ff = root / 'ffmpeg'; ff.mkdir()
                import os
                (ff / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')).write_text('not executable')
                result = download_preflight.tool_status(ff)
                self.assertEqual(result, {'source': 'app_folder', 'ffmpeg': 'found', 'ffprobe': 'missing'})
                self.assertEqual(which.call_count, 2)
            with patch('pathlib.Path.exists', side_effect=PermissionError()):
                self.assertEqual(download_preflight.tool_status(ff)['source'], 'unknown')
