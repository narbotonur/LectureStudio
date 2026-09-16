from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from annie import config as cfg
from annie.whisper_models import complete_model, resolve_model, preparation_status
from annie.whisper_runtime import ModelCache, load_model


def model_folder(path):
    path.mkdir(parents=True, exist_ok=True)
    for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.json'):
        (path / name).write_bytes(b'test-fixture')
    return path


class ResolutionTests(unittest.TestCase):
    def test_complete_legacy_cache_wins_over_partial_new_profile_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            partial = root / 'partial'
            partial.mkdir()
            (partial / 'config.json').write_bytes(b'{}')
            cached = model_folder(root / 'legacy-model')
            new_cache = root / 'profile/model-cache'

            def download(name, **options):
                self.assertTrue(options['local_files_only'], 'Must not redownload cached weights')
                return str(partial if Path(options['cache_dir']) == new_cache else cached)

            with patch.object(cfg, 'DATA_DIR', str(root / 'profile')), \
                 patch.object(cfg, 'MODELS_DIR', str(root / 'models')), \
                 patch('faster_whisper.utils.download_model', side_effect=download) as fetch:
                self.assertEqual(resolve_model('large-v3-turbo'), str(cached.resolve()))
                self.assertEqual(fetch.call_count, 2)

    def test_explicit_complete_model_folder_never_contacts_hub(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = model_folder(Path(temporary) / 'local')
            with patch('faster_whisper.utils.download_model') as fetch:
                self.assertEqual(resolve_model(str(folder)), str(folder.resolve()))
                fetch.assert_not_called()

    def test_partial_or_zero_length_weights_are_not_a_complete_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = model_folder(Path(temporary))
            self.assertTrue(complete_model(folder))
            (folder / 'model.bin').write_bytes(b'')
            self.assertFalse(complete_model(folder))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                resolve_model(str(folder))

    def test_first_download_runs_once_after_offline_cache_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = model_folder(root / 'downloaded')
            report = Mock()
            online_calls = []

            def download(name, **options):
                if options.get('local_files_only'):
                    raise FileNotFoundError('not cached')
                online_calls.append(options)
                return str(folder)

            with patch.object(cfg, 'MODELS_DIR', str(root / 'models')), \
                 patch('faster_whisper.utils.download_model', side_effect=download):
                self.assertEqual(resolve_model('large-v3-turbo', report), str(folder.resolve()))
            self.assertEqual(len(online_calls), 1)
            self.assertIn('Downloading', report.call_args.args[0])


class LoadingTests(unittest.TestCase):
    def test_download_failure_does_not_repeat_as_gpu_fallback(self):
        with patch('annie.whisper_models.resolve_model', side_effect=OSError('network timeout')) as resolve, \
             patch('faster_whisper.WhisperModel') as model:
            with self.assertRaisesRegex(OSError, 'network timeout'):
                load_model('large-v3-turbo')
            resolve.assert_called_once()
            model.assert_not_called()

    def test_constructor_receives_local_path_and_offline_flag(self):
        with patch('annie.whisper_models.resolve_model', return_value='/cached/model'), \
             patch('ctranslate2.get_cuda_device_count', return_value=0), \
             patch('faster_whisper.WhisperModel') as model:
            load_model('large-v3-turbo')
            self.assertEqual(model.call_args.args[0], '/cached/model')
            self.assertTrue(model.call_args.kwargs['local_files_only'])

    def test_status_heartbeat_reports_real_phase_and_stops_at_completion(self):
        events = []
        heartbeat = threading.Event()

        def emitted(kind, **data):
            events.append(data['text'])
            if 'elapsed' in data['text']:
                heartbeat.set()

        with preparation_status('large-v3-turbo', emitted, interval=.01) as report:
            report('Using existing files')
            self.assertTrue(heartbeat.wait(.5), 'Heartbeat thread did not report within timeout')
        count = len(events)
        time.sleep(.03)
        self.assertEqual(len(events), count)
        self.assertTrue(any('Using existing files' in text and 'elapsed' in text for text in events))

    def test_warm_model_is_reused_without_loading_again(self):
        loader = Mock(return_value=(object(), 'CPU'))
        cache = ModelCache(loader)
        first, _, _ = cache.get('large-v3-turbo')
        second, _, reused = cache.get('large-v3-turbo')
        self.assertIs(first, second)
        self.assertTrue(reused)
        loader.assert_called_once()


if __name__ == '__main__':
    unittest.main()
