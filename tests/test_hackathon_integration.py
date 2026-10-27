"""Cross-module regressions for settings refresh and the lecture review flow."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class HackathonIntegrationTests(unittest.TestCase):
    def test_encrypted_meta_key_refreshes_in_warm_process_and_never_enters_json(self):
        from annie import config as cfg
        from annie.secure_storage import read_secret
        with tempfile.TemporaryDirectory() as root, \
             patch.object(cfg, 'SETTINGS_FILE', str(Path(root) / 'settings.json')), \
             patch.object(cfg, 'SECRETS_FILE', str(Path(root) / 'accounts.dpapi')), \
             patch.object(cfg, 'META_API_KEY', 'fixture-meta-secret'), \
             patch.object(cfg, 'GEMINI_API_KEY', ''), patch.object(cfg, 'GROQ_API_KEY', ''), \
             patch.object(cfg, 'WEATHER_API_KEY', ''), patch.object(cfg, 'ELEVENLABS_API_KEY', ''):
            cfg.save_settings()
            self.assertNotIn('fixture-meta-secret', Path(cfg.SETTINGS_FILE).read_text())
            self.assertEqual(read_secret(cfg.SECRETS_FILE)['meta_api_key'], 'fixture-meta-secret')
            cfg.META_API_KEY = 'stale-process-value'
            cfg.load_settings()
            self.assertEqual(cfg.META_API_KEY, 'fixture-meta-secret')
            cfg.META_API_KEY = ''
            cfg.save_settings()
            cfg.META_API_KEY = 'stale-process-value'
            cfg.load_settings()
            self.assertEqual(cfg.META_API_KEY, '')

    def test_finished_transcript_does_not_start_hidden_note_generation(self):
        from annie import config as cfg
        from annie.meeting import AudioFileMeetingWorker
        with tempfile.TemporaryDirectory() as root, patch.object(cfg, 'AUTO_GENERATE_NOTES', False):
            path = Path(root) / 'fixture.wav'
            path.touch()
            worker = AudioFileMeetingWorker(str(path))
            ready = []
            worker.transcript_ready.connect(lambda: ready.append(True))

            def consume(owner, **options):
                owner.full_transcript.append('Final transcript.')
                return {}

            with patch('annie.whisper_events.consume_session', side_effect=consume), \
                 patch('annie.meeting.generate_ai_summary_sync') as generate:
                worker.run()
            self.assertEqual(ready, [True])
            generate.assert_not_called()

    def test_approved_evidence_task_reaches_daily_suggestion_with_stable_identity(self):
        from annie.lecture_actions import ActionStore, extract_actions
        from annie.daily_plan import suggest_today
        import datetime as dt
        from annie.planner import TZ
        segments = [{'start': 0, 'end': 8, 'text': 'Review stack frames before the next class.', 'source': 'fixture'}]
        answer = {'findings': [{'type': 'review_task', 'summary': 'Review stack frames',
            'quote': segments[0]['text'], 't_start': 0, 't_end': 8, 'source': 'fixture',
            'confidence': .8, 'due_at': None, 'minutes': 25, 'suggested_action': 'Trace one procedure call.'}]}
        with tempfile.TemporaryDirectory() as root:
            store = ActionStore(root)
            scan = extract_actions(segments, generator=lambda *_: json.dumps(answer))
            store.add_scan(scan, segments, 'CSCI', 'Fixture lecture')
            self.assertEqual(store.approved_tasks(), [])
            action = store.list_actions('pending')[0]
            store.approve(action['id'])
            items, _ = suggest_today(tasks=store.approved_tasks(), now=dt.datetime(2026, 10, 27, 9, tzinfo=TZ))
            self.assertEqual(items[0]['action_id'], action['id'])
            store.mark_task_done(action['id'])
            self.assertEqual(store.approved_tasks(), [])

    def test_transcript_archive_survives_restart_without_notes_or_api(self):
        from annie.lecture_archive import load_transcript, save_transcript
        segments = [{'start': 0, 'end': 5, 'text': 'Stack frames preserve registers.', 'source': 'fixture.wav'}]
        with tempfile.TemporaryDirectory() as root:
            path = save_transcript(root, segments, 'Fixture lecture', 'CSCI', False)
            saved = load_transcript(path)
            self.assertFalse(saved['complete'])
            self.assertEqual(saved['segments'][0]['text'], segments[0]['text'])
            self.assertEqual(saved['course'], 'CSCI')
            save_transcript(root, segments, 'Fixture lecture', 'CSCI', True)
            self.assertTrue(load_transcript(path)['complete'])


if __name__ == '__main__':
    unittest.main()
